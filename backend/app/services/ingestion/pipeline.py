"""Scene ingestion pipeline (idempotent, resumable, incremental)."""
from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import rasterio
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import IngestionError
from app.core.logging import get_logger
from app.core.security import resolve_safe_path
from app.db.base import utcnow
from app.db.models import Scene, TemporalObservation, Tile
from app.geo import raster
from app.geo.raster import SUPPORTED_EXT
from app.geo.spectral import band_roles
from app.repositories.scene_repository import SceneRepository
from app.repositories.tile_repository import TileRepository
from app.services.embeddings.index_service import EmbeddingIndexService
from app.services.provenance.service import ProvenanceService
from app.services.registry import get_embedding_model, get_quality_model
from app.storage import get_storage

log = get_logger(__name__)
Progress = Callable[[float, str], None]


@dataclass
class IngestResult:
    scene_id: str
    status: str
    created: bool
    duplicate: bool
    tiles_created: int = 0
    tiles_skipped: int = 0
    embeddings_added: int = 0
    message: str = ""
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return self.__dict__.copy()


class IngestionService:
    def __init__(self, db: Session, progress: Progress | None = None):
        self.db = db
        self.s = get_settings()
        self.scenes = SceneRepository(db)
        self.tiles = TileRepository(db)
        self.prov = ProvenanceService(db)
        self.storage = get_storage()
        self.progress = progress or (lambda p, m: None)

    # ------------------------------------------------------------------ single scene
    def ingest_scene(self, path: str, metadata: dict | None = None, force: bool = False) -> IngestResult:
        p = resolve_safe_path(path)
        raster.validate_raster(p)
        self.progress(0.02, "checksum")
        checksum = raster.file_checksum(p)
        scene_id = f"scn_{checksum[:20]}"

        existing = self.scenes.by_checksum(checksum)
        if existing and existing.status == "complete" and not force:
            return IngestResult(existing.scene_id, existing.status, False, True,
                                message="Duplicate: scene already ingested (matched by checksum)")

        meta = raster.extract_metadata(p, metadata)
        if existing is None:
            scene = Scene(
                scene_id=scene_id, source_path=str(p), filename=meta.filename, sensor=meta.sensor,
                platform=meta.platform, acquisition_time=meta.acquisition_time,
                processing_level=meta.processing_level, crs=meta.crs, resolution=meta.resolution,
                width=meta.width, height=meta.height, bands=meta.bands, geometry=meta.footprint_wgs84.wkt,
                cloud_percentage=meta.cloud_percentage, checksum=checksum, status="processing",
                metadata_json={**meta.extra, "dtype": meta.dtype, "nodata": meta.nodata, "is_cog": meta.is_cog,
                               "transform": list(meta.transform), "epsg": meta.epsg,
                               "file_stat": _stat(p), "user_metadata": metadata or {}},
            )
            scene.min_x, scene.min_y, scene.max_x, scene.max_y = meta.footprint_wgs84.bounds
            try:
                self.scenes.add(scene)
                self.prov.record("scene", scene_id, "ingest", scene=scene,
                                 preprocessing_version=self.s.PREPROCESSING_VERSION,
                                 parameters={"metadata_overrides": metadata or {}, "crs": meta.crs,
                                             "resolution": meta.resolution, "bands": meta.bands})
                self.db.commit()
            except IntegrityError:  # concurrent ingest of same file
                self.db.rollback()
                existing = self.scenes.by_checksum(checksum)
                return IngestResult(existing.scene_id, existing.status, False, True,
                                    message="Duplicate: concurrently ingested")
            created = True
        else:
            scene, created = existing, False
            scene.status = "processing"
            self.db.commit()

        try:
            res = self._process(scene, meta)
            res.created = created
            return res
        except Exception as e:
            self.db.rollback()
            scene = self.scenes.get(scene_id)
            scene.status = "failed"
            scene.metadata_json = {**(scene.metadata_json or {}), "error": str(e)[:1000]}
            self.db.commit()
            log.exception(f"ingestion failed for {scene_id}")
            raise IngestionError(f"Ingestion failed for {p.name}: {e}", {"scene_id": scene_id}) from e

    def _process(self, scene: Scene, meta: raster.RasterMetadata) -> IngestResult:
        s = self.s
        model = get_embedding_model()
        minfo = model.info()
        qmodel = get_quality_model()
        index = EmbeddingIndexService(self.db, model)
        res = IngestResult(scene.scene_id, "processing", False, False)

        # Optional scene-level COG copy (RAW/COG storage)
        if not meta.is_cog and s.TILE_FORMAT.upper() == "COG":
            key = f"scenes/{scene.scene_id}.tif"
            if not self.storage.exists(key):
                try:
                    from rasterio.shutil import copy as rio_copy

                    rio_copy(str(meta.path), str(self.storage.get_path(key)), driver="COG", compress="deflate")
                    self.storage.commit(key)
                    scene.metadata_json = {**scene.metadata_json, "cog_path": key}
                except Exception as e:  # keep going with original file
                    res.warnings.append(f"COG conversion skipped: {e}")

        done = self.tiles.existing_ids(scene.scene_id)
        windows = list(raster.grid_windows(meta, s.TILE_SIZE))
        total = len(windows)
        batch: list[tuple[Tile, tuple]] = []
        qualities, clouds = [], []
        batch_no = 0

        with rasterio.open(meta.path) as ds:
            # scene-level reflectance scale from a decimated read (cheap)
            f = max(1, int(max(ds.width, ds.height) / 1024))
            sample = ds.read(out_shape=(ds.count, max(1, ds.height // f), max(1, ds.width // f)))
            scale = raster.reflectance_scale(meta.dtype, float(np.nanmax(sample)) if sample.size else 1.0,
                                             s.REFLECTANCE_SCALE)
            for n, tw in enumerate(windows):
                tile_id = f"{scene.scene_id}_{tw.gx}_{tw.gy}"
                if tile_id in done:
                    t = self.tiles.get(tile_id)
                    if t and t.quality_score is not None:
                        qualities.append(t.quality_score)
                        clouds.append(t.cloud_percentage or 0)
                    # tile exists; embedding may still be missing (resume) -> re-encode below
                    if index.repo.for_tile(tile_id, minfo.name, minfo.version) is None and t:
                        arr, _ = raster.read_raster(self.storage.get_path(t.raster_path))
                        valid = raster.valid_mask(arr, meta.nodata)
                        norm = raster.normalize(arr, valid, scale)
                        mask_arr, _ = raster.read_raster(self.storage.get_path(t.mask_path))
                        batch.append((t, (norm, valid, mask_arr[0] == 0)))
                    continue
                arr = raster.read_window(ds, tw, s.TILE_SIZE, meta.nodata)
                valid = raster.valid_mask(arr, meta.nodata)
                vratio = float(valid.mean())
                if vratio < s.MIN_VALID_PIXEL_RATIO:
                    res.tiles_skipped += 1
                    continue
                norm = raster.normalize(arr, valid, scale)
                q, mask = qmodel.assess(norm, valid)

                rkey = f"tiles/{scene.scene_id}/{tile_id}.tif"
                mkey = f"masks/{scene.scene_id}/{tile_id}_mask.tif"
                tkey = f"thumbnails/{scene.scene_id}/{tile_id}.png"
                raster.write_tile(self.storage.get_path(rkey), arr, tw.transform, ds.crs, meta.nodata, s.TILE_FORMAT)
                raster.write_mask(self.storage.get_path(mkey), mask, tw.transform, ds.crs)
                raster.make_thumbnail(norm, band_roles(norm, s.BAND_MAPPING), s.THUMBNAIL_SIZE,
                                      self.storage.get_path(tkey))
                for k in (rkey, mkey, tkey):
                    self.storage.commit(k)

                geom = raster.to_wgs84_polygon(tw.bounds, ds.crs)
                tile = Tile(
                    tile_id=tile_id, scene_id=scene.scene_id, geometry=geom.wkt, x_index=tw.gx, y_index=tw.gy,
                    width=s.TILE_SIZE, height=s.TILE_SIZE, raster_path=rkey, thumbnail_path=tkey, mask_path=mkey,
                    quality_score=q.overall_quality, cloud_percentage=round(q.cloud_score * 100, 2),
                    valid_pixel_percentage=round(vratio * 100, 2), quality_json=q.to_dict(),
                    location_key=tw.location_key, acquisition_time=scene.acquisition_time,
                    sensor=scene.sensor, platform=scene.platform,
                )
                tile.min_x, tile.min_y, tile.max_x, tile.max_y = geom.bounds
                self.db.add(tile)
                self.db.flush()  # tile row must precede its observation / embedding FKs
                obs = TemporalObservation(
                    tile_id=tile_id, location_key=tw.location_key, location=geom.wkt,
                    acquisition_time=scene.acquisition_time, scene_id=scene.scene_id,
                    quality_score=q.overall_quality, usable_for_change=q.usable_for_change_detection)
                obs.min_x, obs.min_y, obs.max_x, obs.max_y = geom.bounds
                self.db.add(obs)
                self.prov.record("tile", tile_id, "tile_quality", scene=scene,
                                 preprocessing_version=s.PREPROCESSING_VERSION,
                                 parameters={"tile_size": s.TILE_SIZE, "grid": [tw.gx, tw.gy],
                                             "location_key": tw.location_key, "reflectance_scale": scale,
                                             "quality_model": qmodel.info().key, "format": s.TILE_FORMAT,
                                             "quality": q.to_dict() | {"features": None}})
                qualities.append(q.overall_quality)
                clouds.append(q.cloud_score * 100)
                res.tiles_created += 1
                batch.append((tile, (norm, valid, mask == 0)))

                if len(batch) >= s.EMBEDDING_BATCH_SIZE:
                    res.embeddings_added += self._flush(batch, index, scene, batch_no)
                    batch, batch_no = [], batch_no + 1
                    self.progress(0.05 + 0.9 * (n + 1) / total, f"tiles {n + 1}/{total}")
            if batch:
                res.embeddings_added += self._flush(batch, index, scene, batch_no)

        scene = self.scenes.get(scene.scene_id)
        scene.quality_score = round(float(np.mean(qualities)), 4) if qualities else 0.0
        if meta.cloud_percentage is None:
            scene.cloud_percentage = round(float(np.mean(clouds)), 2) if clouds else None
        scene.status = "complete"
        scene.ingestion_timestamp = utcnow()
        self.prov.record("scene", scene.scene_id, "ingest_complete", scene=scene,
                         preprocessing_version=s.PREPROCESSING_VERSION, embedding_model=minfo.name,
                         embedding_version=minfo.version,
                         parameters={"tiles_created": res.tiles_created, "tiles_skipped": res.tiles_skipped,
                                     "embeddings_added": res.embeddings_added})
        self.db.commit()
        self.progress(1.0, "complete")
        res.status = "complete"
        res.message = f"Ingested {res.tiles_created} tiles"
        return res

    def _flush(self, batch, index: EmbeddingIndexService, scene: Scene, batch_no: int) -> int:
        self.db.flush()  # tiles must exist before embedding FKs
        model = index.model
        vecs = model.encode_images([(norm, valid, clear) for _, (norm, valid, clear) in batch])
        rows = index.add_tile_vectors([t.tile_id for t, _ in batch], vecs, f"{scene.scene_id}/b{batch_no:05d}")
        for r in rows:
            self.prov.record("embedding", r.tile_id, "embed", scene=scene,
                             preprocessing_version=self.s.PREPROCESSING_VERSION,
                             embedding_model=r.model_name, embedding_version=r.model_version,
                             parameters={"vector_id": r.vector_id, "dimension": r.dimension,
                                         "checksum": index.info.checksum})
        self.db.commit()
        index.persist()  # after DB commit; reconcile() repairs if we crash in between
        return len(rows)

    # ------------------------------------------------------------------ batch / incremental
    def ingest_batch(self, paths: list[str], metadata: dict | None = None, force: bool = False) -> dict:
        results, errors = [], []
        for i, path in enumerate(paths):
            self.progress(i / max(len(paths), 1), f"scene {i + 1}/{len(paths)}")
            try:
                results.append(self.ingest_scene(path, metadata, force).to_dict())
            except Exception as e:
                self.db.rollback()
                errors.append({"path": path, "error": getattr(e, "message", str(e))})
        self.progress(1.0, "complete")
        return {"requested": len(paths), "succeeded": len(results), "failed": len(errors),
                "duplicates": sum(r["duplicate"] for r in results), "results": results, "errors": errors}

    def discover(self, directories: list[str] | None = None) -> list[str]:
        """Find imagery not yet ingested (or changed on disk since ingestion)."""
        roots = []
        for d in directories or self.s.INCREMENTAL_SCAN_DIRS:
            p = Path(d)
            roots.append(resolve_safe_path(str(p if p.is_absolute() else Path(self.s.DATA_ROOT) / p)))
        known: dict[str, dict] = {}
        from sqlalchemy import select

        for sp, status, mj in self.db.execute(select(Scene.source_path, Scene.status, Scene.metadata_json)):
            known[sp] = {"status": status, "stat": (mj or {}).get("file_stat")}
        new = []
        for root in roots:
            if not root.exists():
                continue
            for f in sorted(root.rglob("*")):
                if not f.is_file() or f.suffix.lower() not in SUPPORTED_EXT or ".tmp" in f.name:
                    continue
                k = known.get(str(f.resolve()))
                if k and k["status"] == "complete" and k["stat"] == _stat(f):
                    continue  # unchanged & done -> no re-hash
                new.append(str(f.resolve()))
        return new

    def ingest_incremental(self, directories: list[str] | None = None, metadata: dict | None = None) -> dict:
        paths = self.discover(directories)
        out = self.ingest_batch(paths, metadata) if paths else {
            "requested": 0, "succeeded": 0, "failed": 0, "duplicates": 0, "results": [], "errors": []}
        out["discovered"] = paths
        out["index_rebuilt"] = False  # incremental: vectors appended only
        return out


def _stat(p: Path) -> dict:
    st = p.stat()
    return {"size": st.st_size, "mtime": math.floor(st.st_mtime)}
