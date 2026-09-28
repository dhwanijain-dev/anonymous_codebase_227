"""Temporal change analysis engine.

AOI -> observations (PostGIS) -> group by location -> chronological sort -> quality gate
-> candidate pairs -> align/normalise -> detector -> temporal consensus -> confidence
-> earliest supported observation -> persisted analyses with evidence + provenance.

change_confidence = base_change_score * quality_factor * registration_factor
                    * temporal_consistency_factor   (* pair-level suppression factors)
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np
from shapely.geometry import box
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.db.models import ChangeAnalysis, ChangeEvidence, Scene, TemporalObservation, Tile
from app.geo import raster
from app.models.change_model import BaseChangeDetector, Observation, PairResult
from app.repositories.tile_repository import TileRepository
from app.services.provenance.service import ProvenanceService
from app.services.registry import get_change_detector
from app.storage import get_storage

log = get_logger(__name__)


@dataclass
class LocationSeries:
    location_key: str
    items: list[tuple[TemporalObservation, Tile]]
    dropped: list[dict] = field(default_factory=list)


@dataclass
class LocationChange:
    location_key: str
    change_type: str
    confidence: float
    base_score: float
    earliest: tuple[TemporalObservation, Tile] | None
    last_unchanged: tuple[TemporalObservation, Tile] | None
    evidence: list[tuple[tuple, tuple, PairResult]]
    factors: dict
    geometry_wkt: str | None
    quality: float


class ChangeAnalysisService:
    def __init__(self, db: Session, detector: BaseChangeDetector | None = None):
        self.db = db
        self.s = get_settings()
        self.detector = detector or get_change_detector()
        self.info = self.detector.info()
        self.tiles = TileRepository(db)
        self.prov = ProvenanceService(db)
        self._cache: dict[str, Observation] = {}

    # ------------------------------------------------------------------ loading
    def _load(self, obs: TemporalObservation, tile: Tile, scene: Scene | None) -> tuple[Observation, dict]:
        st = get_storage()
        arr, meta = raster.read_raster(st.get_path(tile.raster_path))
        valid = raster.valid_mask(arr, meta["nodata"])
        scale = raster.reflectance_scale(meta["dtype"], float(arr.max()) if arr.size else 1, self.s.REFLECTANCE_SCALE)
        norm = raster.normalize(arr, valid, scale)
        mask, _ = raster.read_raster(st.get_path(tile.mask_path)) if tile.mask_path else (np.zeros((1, *valid.shape), np.uint8), None)
        extra = (scene.metadata_json or {}) if scene else {}
        return Observation(norm, valid, mask[0], obs.acquisition_time, tile.sensor, tile.platform,
                           obs.quality_score or 0.0, {k: extra.get(k) for k in ("view_off_nadir", "sun_elevation")}), meta

    # ------------------------------------------------------------------ pipeline
    def analyze(self, bbox: list[float] | None, start: datetime | None, end: datetime | None,
                change_types: list[str] | None = None, min_quality: float | None = None,
                location_keys: list[str] | None = None, persist: bool = True,
                request_id: str | None = None) -> dict:
        if not bbox and not location_keys:
            raise ValidationError("Either bbox or location_keys is required")
        if start and end and start >= end:
            raise ValidationError("start_date must be before end_date")
        min_q = self.s.QUALITY_MIN_FOR_CHANGE if min_quality is None else min_quality
        request_id = request_id or f"req_{uuid.uuid4().hex[:16]}"

        # 1. observations intersecting AOI
        rows = self.tiles.observations(bbox, start, end, location_keys)
        # 2. group by location, 3. sort chronologically
        groups: dict[str, list] = defaultdict(list)
        for obs, tile in rows:
            groups[obs.location_key].append((obs, tile))
        scenes = {s.scene_id: s for s in self.db.scalars(
            select(Scene).where(Scene.scene_id.in_({o.scene_id for o, _ in rows})))} if rows else {}

        detections: list[LocationChange] = []
        diagnostics = {"observations": len(rows), "locations": len(groups), "dropped_low_quality": 0,
                       "locations_insufficient": 0, "pairs_evaluated": 0}
        for key, items in groups.items():
            items.sort(key=lambda x: (x[0].acquisition_time or datetime.min.replace(tzinfo=timezone.utc), x[1].tile_id))
            # 4. quality gate BEFORE change detection
            good = [(o, t) for o, t in items if o.usable_for_change and (o.quality_score or 0) >= min_q]
            diagnostics["dropped_low_quality"] += len(items) - len(good)
            if len(good) < 2:
                diagnostics["locations_insufficient"] += 1
                continue
            det = self._analyze_location(key, good, scenes, diagnostics)
            if det and (not change_types or det.change_type in change_types) \
                    and det.confidence >= self.s.CHANGE_MIN_REPORT_CONFIDENCE:
                detections.append(det)

        detections.sort(key=lambda d: -d.confidence)
        analyses = [self._persist(d, start, end, request_id) if persist else self._to_dict(d, None, start, end)
                    for d in detections]
        if persist:
            self.db.commit()
        self._cache.clear()
        return {"request_id": request_id, "detections": analyses, "diagnostics": diagnostics,
                "parameters": {"bbox": bbox, "start_date": start, "end_date": end, "change_types": change_types,
                               "min_quality": min_q}, "model": self.info.to_dict()}

    def _analyze_location(self, key: str, items: list, scenes: dict, diag: dict) -> LocationChange | None:
        # 5. candidate pairs: reference = best of the earliest observations; compare forward in time
        head = items[: max(1, len(items) // 3)]
        ref = max(head, key=lambda x: x[0].quality_score or 0)
        ref_idx = items.index(ref)
        later = items[ref_idx + 1:]
        if not later:
            return None
        cap = self.s.CHANGE_MAX_PAIRS_PER_LOCATION
        if len(later) > cap:
            idx = np.linspace(0, len(later) - 1, cap).round().astype(int)
            later = [later[i] for i in sorted(set(idx))]

        ref_obs, ref_meta = self._obs(ref, scenes)
        pairs: list[tuple[tuple, PairResult]] = []
        for it in later:
            o, meta = self._obs(it, scenes)
            # 6. align (reproject if grids differ) — 7-9 normalise/diff/estimate in detector
            if meta["transform"] != ref_meta["transform"] or o.image.shape != ref_obs.image.shape:
                shape = ref_obs.image.shape[1:]
                o = Observation(raster.align_to(o.image, meta, ref_meta, shape),
                                raster.align_to(o.valid[None].astype(np.uint8), meta, ref_meta, shape)[0] > 0,
                                raster.align_to(o.mask[None], meta, ref_meta, shape)[0],
                                o.time, o.sensor, o.platform, o.quality, o.extra)
            pairs.append((it, self.detector.compare(ref_obs, o)))
            diag["pairs_evaluated"] += 1

        thr = self.s.CHANGE_THRESHOLD
        flags = [p.score >= thr for _, p in pairs]
        if not any(flags):
            return None
        # 12. earliest supported observation — temporal consensus: the earliest flagged
        # observation that is followed by persistence >= 0.5 (else the first flag, marked transient)
        first = flags.index(True)
        for i in range(first, len(pairs)):
            if flags[i]:
                tail = flags[i:]
                if sum(tail) / len(tail) >= 0.5:
                    first = i
                    break
        after = pairs[first:]
        supporting = [(it, p) for it, p in after if p.score >= thr]
        persistence = len(supporting) / len(after)
        n_sup = len(supporting)

        # 10. classify: quality/score-weighted vote over supporting pairs
        votes: dict[str, float] = defaultdict(float)
        for it, p in supporting:
            votes[p.change_type] += p.score * (it[0].quality_score or 0.5)
        ctype = max(votes, key=votes.get)
        agreement = votes[ctype] / max(sum(votes.values()), 1e-9)

        # 11. confidence. Pair scores include registration suppression; divide it out so the
        # explicit registration_factor below is not double-counted.
        base = float(np.clip(np.median([p.score / max(p.factors.get("registration_factor", 1.0), 1e-6)
                                        for _, p in supporting]), 0, 1))
        sup_quality = float(np.mean([it[0].quality_score or 0 for it, _ in supporting]))
        quality_factor = float(np.clip(0.5 * (ref[0].quality_score or 0) + 0.5 * sup_quality, 0, 1))
        registration_factor = float(np.min([p.factors.get("registration_factor", 1.0) for _, p in supporting]))
        tcf = persistence * min(1.0, 0.55 + 0.15 * n_sup)
        if n_sup == 1:
            tcf *= 0.5 + 0.5 * sup_quality  # single observation: penalise, more so if low quality
            transient = len(after) > 1
        else:
            transient = persistence < 0.5
        if transient:
            tcf *= 0.5
        confidence = float(np.clip(base * quality_factor * registration_factor * tcf
                                   * (0.7 + 0.3 * agreement), 0, 1))
        factors = {
            "base_change_score": round(base, 4), "quality_factor": round(quality_factor, 4),
            "registration_factor": round(registration_factor, 4),
            "temporal_consistency_factor": round(tcf, 4), "type_agreement": round(agreement, 4),
            "persistence": round(persistence, 4), "supporting_observations": n_sup,
            "observations_after_onset": len(after), "transient": transient,
            "pair_factors": pairs[first][1].factors,
        }
        earliest = pairs[first][0]
        last_unchanged = pairs[first - 1][0] if first > 0 else ref
        return LocationChange(key, ctype, round(confidence, 4), round(base, 4), earliest, last_unchanged,
                              [(ref, it, p) for it, p in pairs], factors,
                              self._change_geometry(earliest[1], pairs[first][1]), round(quality_factor, 4))

    def _obs(self, item, scenes) -> tuple[Observation, dict]:
        obs, tile = item
        if tile.tile_id not in self._cache:
            self._cache[tile.tile_id] = self._load(obs, tile, scenes.get(tile.scene_id))
        return self._cache[tile.tile_id]

    @staticmethod
    def _change_geometry(tile: Tile, pr: PairResult) -> str | None:
        """Footprint of changed pixels (bbox) mapped into the tile's WGS84 extent."""
        if pr.changed_mask is None or not pr.changed_mask.any() or tile.min_x is None:
            return tile.geometry
        rows, cols = np.where(pr.changed_mask)
        h, w = pr.changed_mask.shape
        fx = lambda c: tile.min_x + (tile.max_x - tile.min_x) * c / w  # noqa: E731
        fy = lambda r: tile.max_y - (tile.max_y - tile.min_y) * r / h  # noqa: E731
        return box(fx(cols.min()), fy(rows.max() + 1), fx(cols.max() + 1), fy(rows.min())).wkt

    # ------------------------------------------------------------------ persistence
    def _persist(self, d: LocationChange, start, end, request_id) -> dict:
        aid = f"chg_{uuid.uuid4().hex[:20]}"
        ca = ChangeAnalysis(
            analysis_id=aid, request_id=request_id, geometry=d.geometry_wkt, location_key=d.location_key,
            start_time=start, end_time=end,
            earliest_supported_time=d.earliest[0].acquisition_time if d.earliest else None,
            change_type=d.change_type, confidence=d.confidence, quality_score=d.quality,
            status="pending_review", model_name=self.info.name, model_version=self.info.version,
            factors_json=d.factors | {"last_unchanged_time": (
                d.last_unchanged[0].acquisition_time.isoformat()
                if d.last_unchanged and d.last_unchanged[0].acquisition_time else None)},
        )
        if d.geometry_wkt:
            from shapely import wkt

            ca.min_x, ca.min_y, ca.max_x, ca.max_y = wkt.loads(d.geometry_wkt).bounds
        self.db.add(ca)
        self.db.flush()
        for ref, it, p in d.evidence:
            self.db.add(ChangeEvidence(
                analysis_id=aid, before_tile_id=ref[1].tile_id, after_tile_id=it[1].tile_id,
                before_time=ref[0].acquisition_time, after_time=it[0].acquisition_time,
                evidence_score=p.score,
                processing_metadata={"raw_score": p.raw_score, "changed_fraction": p.changed_fraction,
                                     "change_type": p.change_type, "type_scores": p.type_scores,
                                     "factors": p.factors, "diagnostics": p.diagnostics,
                                     "before_scene": ref[1].scene_id, "after_scene": it[1].scene_id}))
        src = self.db.scalar(select(Scene).where(Scene.scene_id == d.earliest[1].scene_id)) if d.earliest else None
        self.prov.record("change_analysis", aid, "change_detection", scene=src,
                         change_model=self.info.name, change_model_version=self.info.version,
                         preprocessing_version=self.s.PREPROCESSING_VERSION,
                         parameters={"threshold": self.s.CHANGE_THRESHOLD, "request_id": request_id,
                                     "location_key": d.location_key, "model_checksum": self.info.checksum,
                                     "evidence_tiles": sorted({e[1][1].tile_id for e in d.evidence}
                                                              | {e[0][1].tile_id for e in d.evidence})})
        self.db.flush()
        return self._to_dict(d, aid, start, end)

    def _to_dict(self, d: LocationChange, aid, start, end) -> dict:
        return {
            "analysis_id": aid, "change_type": d.change_type, "confidence": d.confidence,
            "earliest_supported_time": d.earliest[0].acquisition_time if d.earliest else None,
            "last_unchanged_time": d.last_unchanged[0].acquisition_time if d.last_unchanged else None,
            "geometry": raster.geojson(d.geometry_wkt), "location_key": d.location_key,
            "start_time": start, "end_time": end, "quality_score": d.quality, "factors": d.factors,
            "evidence": [{"before_scene": ref[1].scene_id, "after_scene": it[1].scene_id,
                          "before_tile": ref[1].tile_id, "after_tile": it[1].tile_id,
                          "before_time": ref[0].acquisition_time, "after_time": it[0].acquisition_time,
                          "score": p.score, "change_type": p.change_type} for ref, it, p in d.evidence],
        }

    # ------------------------------------------------------------------ read
    def get(self, analysis_id: str) -> dict:
        ca = self.db.scalar(select(ChangeAnalysis).where(ChangeAnalysis.analysis_id == analysis_id))
        if ca is None:
            raise NotFoundError(f"Change analysis '{analysis_id}' not found")
        return self.serialize(ca)

    def serialize(self, ca: ChangeAnalysis, with_provenance: bool = True) -> dict:
        ev = sorted(ca.evidence, key=lambda e: (e.after_time or datetime.min.replace(tzinfo=timezone.utc)))
        out = {
            "analysis_id": ca.analysis_id, "request_id": ca.request_id, "change_type": ca.change_type,
            "confidence": ca.confidence, "earliest_supported_time": ca.earliest_supported_time,
            "last_unchanged_time": (ca.factors_json or {}).get("last_unchanged_time"),
            "geometry": raster.geojson(ca.geometry), "location_key": ca.location_key,
            "start_time": ca.start_time, "end_time": ca.end_time, "quality_score": ca.quality_score,
            "status": ca.status, "model_name": ca.model_name, "model_version": ca.model_version,
            "factors": ca.factors_json, "created_at": ca.created_at,
            "evidence": [{"before_scene": e.processing_metadata.get("before_scene"),
                          "after_scene": e.processing_metadata.get("after_scene"),
                          "before_tile": e.before_tile_id, "after_tile": e.after_tile_id,
                          "before_time": e.before_time, "after_time": e.after_time, "score": e.evidence_score,
                          "change_type": e.processing_metadata.get("change_type")} for e in ev],
        }
        if with_provenance:
            out["provenance"] = self.prov.compact("change_analysis", ca.analysis_id)
        return out
