"""Query orchestrator: two-stage retrieval.

Stage 1 (cheap): ANN over the vector index + PostGIS metadata/spatial/temporal/quality
filtering. Chooses *filter-first exact scoring* when filters are selective and
*ANN-first with progressive widening* otherwise.
Stage 2 (expensive, bounded): component scoring, temporal change verification for the
top candidates only, feedback penalty, weighted reranking, persistence + provenance.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import NotFoundError, ValidationError
from app.db.models import AnalystReview, Scene, SearchQuery, SearchResult, Tile
from app.geo import raster
from app.models.query_parser import ParsedQuery
from app.models.reranker import Candidate
from app.repositories.embedding_repository import EmbeddingRepository
from app.services.change_detection.service import ChangeAnalysisService
from app.services.provenance.service import ProvenanceService
from app.services.registry import get_change_detector, get_embedding_model, get_query_parser, get_ranker, get_vector_store
from app.vector.metadata_filter import MetadataFilter, TileFilter

# parser context word -> tile feature that evidences it
CONTEXT_FEATURES = {
    "water_frac": {"water", "river", "rivers", "lake", "lakes", "reservoir", "sea", "coast", "coastline",
                   "shoreline", "pond", "canal", "wetland"},
    "veg_frac": {"vegetation", "forest", "forests", "trees", "crop", "crops", "farmland", "field", "fields"},
    "built_frac": {"building", "buildings", "urban", "settlement", "town", "city"},
    "linearity": {"road", "roads", "highway", "railway", "runway"},
}


@dataclass
class SearchParams:
    top_k: int = 20
    date_from: datetime | None = None
    date_to: datetime | None = None
    sensor: str | None = None
    platform: str | None = None
    bbox: list[float] | None = None
    min_quality: float | None = None
    max_cloud: float | None = None
    require_change: bool = False
    change_types: list[str] | None = None
    group_by_location: bool = True
    exclude_tile_ids: list[str] | None = None

    def tile_filter(self) -> TileFilter:
        return TileFilter(bbox=self.bbox, date_from=self.date_from, date_to=self.date_to, sensor=self.sensor,
                          platform=self.platform, min_quality=self.min_quality, max_cloud=self.max_cloud,
                          exclude_tile_ids=self.exclude_tile_ids)


def _jsonable(d: dict) -> dict:
    return {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in d.items() if v is not None}


class RetrievalService:
    def __init__(self, db: Session):
        self.db = db
        self.s = get_settings()
        self.model = get_embedding_model()
        self.minfo = self.model.info()
        self.store = get_vector_store(self.model)
        self.mf = MetadataFilter(db, self.minfo.name, self.minfo.version)
        self.emb = EmbeddingRepository(db)
        self.ranker = get_ranker()
        self.prov = ProvenanceService(db)

    # ------------------------------------------------------------------ entry points
    def search_text(self, text: str, p: SearchParams) -> dict:
        if not text.strip():
            raise ValidationError("query must not be empty")
        parsed = get_query_parser().parse(text)
        # parser-derived date hints only fill gaps; explicit filters win
        p.date_from = p.date_from or parsed.date_from
        p.date_to = p.date_to or parsed.date_to
        if p.require_change and not p.change_types and parsed.change_types:
            p.change_types = [c for c in parsed.change_types if c != "appearance"] or parsed.change_types
        q = self.model.encode_text(parsed.embedding_text or text)
        return self._run(q, p, "text", text, parsed)

    def search_image(self, image: np.ndarray, valid: np.ndarray | None, p: SearchParams, label: str) -> dict:
        q = self.model.encode_image(image, valid)
        return self._run(q, p, "image", label, None)

    def similar_to_tile(self, tile_id: str, p: SearchParams) -> dict:
        e = self.emb.for_tile(tile_id, self.minfo.name, self.minfo.version)
        if e is None or not self.store.contains(e.vector_id):
            raise NotFoundError(f"No embedding for tile '{tile_id}' under model {self.minfo.key}")
        q = self.store.get_vectors([e.vector_id])[0]
        src = self.db.scalar(select(Tile).where(Tile.tile_id == tile_id))
        # exclude the same location (other dates of the same place are not "similar sites")
        same = list(self.db.scalars(select(Tile.tile_id).where(Tile.location_key == src.location_key))) \
            if src and src.location_key else [tile_id]
        p.exclude_tile_ids = list(set((p.exclude_tile_ids or []) + same))
        return self._run(q, p, "similar_site", tile_id, None)

    # ------------------------------------------------------------------ stage 1
    def _candidates(self, q: np.ndarray, p: SearchParams, pool: int) -> tuple[list[tuple[Tile, float]], dict]:
        f = p.tile_filter()
        stats: dict = {"index_size": self.store.count()}
        if not f.is_empty():
            n = self.mf.count(f)
            stats["filter_matches"] = n
            if n == 0:
                return [], stats | {"strategy": "filter_first"}
            if n <= self.s.FILTER_FIRST_THRESHOLD:
                ids = self.mf.matching_vector_ids(f, n)
                hits = self.store.score_subset(q, ids)[: pool * 4]
                vmap = self.emb.vector_map([h.vector_id for h in hits], self.minfo.name, self.minfo.version)
                tiles = self.mf.filter_candidates(list(set(vmap.values())), f)
                out = [(tiles[vmap[h.vector_id]], h.score) for h in hits
                       if h.vector_id in vmap and vmap[h.vector_id] in tiles]
                return out, stats | {"strategy": "filter_first", "scored": len(ids)}
        k = min(max(pool * self.s.ANN_OVERSAMPLE, pool), max(stats["index_size"], 1))
        while True:
            hits = self.store.search(q, k)
            vmap = self.emb.vector_map([h.vector_id for h in hits], self.minfo.name, self.minfo.version)
            tiles = self.mf.filter_candidates(list(set(vmap.values())), f)
            out, seen = [], set()
            for h in hits:
                tid = vmap.get(h.vector_id)  # DB is authoritative; unknown ids are orphans
                if tid in tiles and tid not in seen:
                    seen.add(tid)
                    out.append((tiles[tid], h.score))
            if len(out) >= pool or k >= stats["index_size"] or k >= self.s.ANN_MAX_CANDIDATES:
                return out, stats | {"strategy": "ann_first", "ann_k": k, "ann_hits": len(hits)}
            k = min(k * 4, self.s.ANN_MAX_CANDIDATES, stats["index_size"])

    # ------------------------------------------------------------------ stage 2
    def _run(self, q: np.ndarray, p: SearchParams, qtype: str, text: str, parsed: ParsedQuery | None) -> dict:
        if not 1 <= p.top_k <= 500:
            raise ValidationError("top_k must be between 1 and 500")
        if p.bbox and (len(p.bbox) != 4 or p.bbox[0] > p.bbox[2] or p.bbox[1] > p.bbox[3]):
            raise ValidationError("bbox must be [min_lon, min_lat, max_lon, max_lat]")
        pool = p.top_k * 3
        cands, stats = self._candidates(q, p, pool)
        cands = cands[:pool]
        now = datetime.now(timezone.utc)

        applicable = {"semantic", "quality", "metadata"}
        if p.bbox:
            applicable.add("spatial")
        temporal_intent = bool(parsed and parsed.temporal_intent) or bool(p.date_from or p.date_to)
        if temporal_intent:
            applicable.add("temporal")
        if p.require_change:
            applicable.add("change")

        times = sorted(t.acquisition_time for t, _ in cands if t.acquisition_time)
        penalties = self._feedback_penalties([t.tile_id for t, _ in cands])
        items: list[Candidate] = []
        for tile, sim in cands:
            sc = {"semantic": float(np.clip(sim, 0, 1)), "quality": float(tile.quality_score or 0),
                  "metadata": self._metadata_score(tile, p, parsed)}
            if p.bbox:
                sc["spatial"] = self._spatial_score(tile, p.bbox)
            if temporal_intent:
                sc["temporal"] = self._temporal_score(tile, times, now)
            items.append(Candidate(tile.tile_id, sc, set(applicable), penalties.get(tile.tile_id, 0.0),
                                   payload={"tile": tile}))

        change_meta = {}
        if p.require_change and items:
            items, change_meta = self._verify_change(items, p)

        ranked = self.ranker.rank(items)
        if p.group_by_location:
            seen, grouped = set(), []
            for c in ranked:
                k = c.payload["tile"].location_key or c.tile_id
                if k not in seen:
                    seen.add(k)
                    grouped.append(c)
            ranked = grouped
        ranked = ranked[: p.top_k]
        return self._persist(qtype, text, p, parsed, ranked, stats | change_meta)

    def _verify_change(self, items: list[Candidate], p: SearchParams) -> tuple[list[Candidate], dict]:
        # only the best preliminary candidates reach the expensive temporal engine
        prelim = self.ranker.rank(items)
        budget, keys = self.s.MAX_CHANGE_CANDIDATES, []
        for c in prelim:
            k = c.payload["tile"].location_key
            if k and k not in keys:
                keys.append(k)
            if len(keys) >= budget:
                break
        svc = ChangeAnalysisService(self.db)
        res = svc.analyze(None, p.date_from, p.date_to, p.change_types, p.min_quality, location_keys=keys)
        by_loc = {d["location_key"]: d for d in res["detections"]}
        kept = []
        for c in items:
            d = by_loc.get(c.payload["tile"].location_key)
            if not d:
                continue
            t = c.payload["tile"]
            # show the observation that evidences the change (at/after onset)
            if d["earliest_supported_time"] and t.acquisition_time and t.acquisition_time < d["earliest_supported_time"]:
                continue
            c.scores["change"] = d["confidence"]
            c.payload["change"] = d
            kept.append(c)
        return kept, {"change_request_id": res["request_id"], "change_locations_checked": len(keys),
                      "change_detections": len(by_loc), "change_diagnostics": res["diagnostics"]}

    # ------------------------------------------------------------------ component scores
    def _metadata_score(self, tile: Tile, p: SearchParams, parsed: ParsedQuery | None) -> float:
        parts = []
        if p.sensor:
            parts.append(1.0 if (tile.sensor or "").lower() == p.sensor.lower() else 0.0)
        if p.platform:
            parts.append(1.0 if (tile.platform or "").lower() == p.platform.lower() else 0.0)
        parts.append(float(np.clip(1 - (tile.cloud_percentage or 0) / 100, 0, 1)))
        parts.append(float(np.clip((tile.valid_pixel_percentage or 0) / 100, 0, 1)))
        feats = (tile.quality_json or {}).get("features") or {}
        if parsed and parsed.context:
            for feat, words in CONTEXT_FEATURES.items():
                if any(w in words for w in parsed.context):
                    v = float(feats.get(feat, 0.0))
                    thr = 0.4 if feat == "linearity" else 0.02
                    parts.append(1.0 if v >= thr else float(np.clip(v / thr, 0, 1)) * 0.5)
        return round(float(np.mean(parts)), 4)

    @staticmethod
    def _spatial_score(tile: Tile, bbox: list[float]) -> float:
        if tile.min_x is None:
            return 0.0
        ix = max(0.0, min(tile.max_x, bbox[2]) - max(tile.min_x, bbox[0]))
        iy = max(0.0, min(tile.max_y, bbox[3]) - max(tile.min_y, bbox[1]))
        area = (tile.max_x - tile.min_x) * (tile.max_y - tile.min_y)
        return round(float(np.clip(ix * iy / area, 0, 1)) if area > 0 else 0.0, 4)

    @staticmethod
    def _temporal_score(tile: Tile, times: list[datetime], now: datetime) -> float:
        if not tile.acquisition_time or not times:
            return 0.5
        if len(times) == 1:
            return 1.0
        rank = sum(1 for t in times if t <= tile.acquisition_time) / len(times)
        return round(float(rank), 4)  # recency within the candidate set

    def _feedback_penalties(self, tile_ids: list[str]) -> dict[str, float]:
        w = self.s.FEEDBACK_REJECT_PENALTY
        if w <= 0 or not tile_ids:
            return {}
        rows = self.db.execute(
            select(SearchResult.tile_id, func.count()).join(AnalystReview, AnalystReview.result_id == SearchResult.result_id)
            .where(SearchResult.tile_id.in_(tile_ids), AnalystReview.decision == "reject")
            .group_by(SearchResult.tile_id)).tuples()
        return {t: min(0.9, w * n) for t, n in rows}

    # ------------------------------------------------------------------ persist + serialize
    def _persist(self, qtype, text, p: SearchParams, parsed, ranked: list[Candidate], stats: dict) -> dict:
        qid = f"qry_{uuid.uuid4().hex[:20]}"
        sq = SearchQuery(query_id=qid, query_text=text, query_type=qtype,
                         filters_json=_jsonable({k: v for k, v in p.__dict__.items()}),
                         parsed_json=parsed.model_dump(mode="json") if parsed else {},
                         embedding_model=self.minfo.key)
        self.db.add(sq)
        self.db.flush()
        self.prov.record("search_query", qid, "search", embedding_model=self.minfo.name,
                         embedding_version=self.minfo.version,
                         parameters={"ranker": self.ranker.info().key, "weights": getattr(self.ranker, "weights", {}), "stats": _jsonable(
                             {k: v for k, v in stats.items() if not isinstance(v, dict)}),
                             "query_type": qtype})
        scenes = {s.scene_id: s for s in self.db.scalars(select(Scene).where(
            Scene.scene_id.in_({c.payload["tile"].scene_id for c in ranked})))} if ranked else {}
        cinfo = get_change_detector().info()
        results = []
        for rank, c in enumerate(ranked, 1):
            t: Tile = c.payload["tile"]
            ch = c.payload.get("change")
            rid = f"res_{uuid.uuid4().hex[:20]}"
            self.db.add(SearchResult(
                result_id=rid, query_id=qid, tile_id=t.tile_id,
                change_analysis_id=ch["analysis_id"] if ch else None,
                semantic_score=c.scores.get("semantic", 0), metadata_score=c.scores.get("metadata", 0),
                quality_score=c.scores.get("quality", 0), change_score=c.scores.get("change", 0),
                spatial_score=c.scores.get("spatial", 0), temporal_score=c.scores.get("temporal", 0),
                final_score=c.final_score, rank=rank))
            sc = scenes.get(t.scene_id)
            self.prov.record("search_result", rid, "rank", scene=sc, embedding_model=self.minfo.name,
                             embedding_version=self.minfo.version,
                             change_model=cinfo.name if ch else None,
                             change_model_version=cinfo.version if ch else None,
                             preprocessing_version=self.s.PREPROCESSING_VERSION,
                             parameters={"scores": c.scores, "final_score": c.final_score, "rank": rank},
                             parent=f"tile:{t.tile_id}")
            results.append(self._serialize(rid, rank, c, t, sc, ch))
        self.db.commit()
        return {"query_id": qid, "query_type": qtype, "query": text,
                "parsed_query": parsed.model_dump() if parsed else None, "total": len(results),
                "results": results, "stats": stats,
                "embedding_model": {"name": self.minfo.name, "version": self.minfo.version}}

    def _serialize(self, rid, rank, c: Candidate, t: Tile, sc: Scene | None, ch: dict | None) -> dict:
        return {
            "result_id": rid, "rank": rank, "tile_id": t.tile_id, "scene_id": t.scene_id,
            "geometry": raster.geojson(t.geometry), "bbox": t.bbox, "location_key": t.location_key,
            "acquisition_time": t.acquisition_time, "sensor": t.sensor, "platform": t.platform,
            "semantic_score": round(c.scores.get("semantic", 0), 4),
            "quality_score": round(c.scores.get("quality", 0), 4),
            "metadata_score": round(c.scores.get("metadata", 0), 4),
            "spatial_score": c.scores.get("spatial"), "temporal_score": c.scores.get("temporal"),
            "change_score": round(c.scores.get("change", 0), 4),
            "final_score": c.final_score, "confidence": c.confidence,
            "change": {k: ch[k] for k in ("analysis_id", "change_type", "confidence", "earliest_supported_time")}
            if ch else None,
            "thumbnail_url": f"{self.s.API_PREFIX}/tiles/{t.tile_id}/thumbnail",
            "thumbnail_path": t.thumbnail_path,
            "provenance": {
                "href": f"{self.s.API_PREFIX}/provenance/search_result/{rid}",
                "source_scene_id": t.scene_id, "source_path": sc.source_path if sc else None,
                "checksum": sc.checksum if sc else None,
                "embedding_model": self.minfo.name, "embedding_version": self.minfo.version,
                "preprocessing_version": self.s.PREPROCESSING_VERSION,
            },
        }

    # ------------------------------------------------------------------ read back
    def get_query(self, query_id: str) -> dict:
        sq = self.db.scalar(select(SearchQuery).where(SearchQuery.query_id == query_id))
        if sq is None:
            raise NotFoundError(f"Search query '{query_id}' not found")
        rows = sorted(sq.results, key=lambda r: r.rank)
        tiles = {t.tile_id: t for t in self.db.scalars(select(Tile).where(Tile.tile_id.in_([r.tile_id for r in rows])))}
        scenes = {s.scene_id: s for s in self.db.scalars(select(Scene).where(
            Scene.scene_id.in_({t.scene_id for t in tiles.values()})))} if tiles else {}
        out = []
        for r in rows:
            t = tiles.get(r.tile_id)
            c = Candidate(r.tile_id, {"semantic": r.semantic_score, "quality": r.quality_score,
                                      "metadata": r.metadata_score, "change": r.change_score,
                                      "spatial": r.spatial_score, "temporal": r.temporal_score},
                          final_score=r.final_score, confidence=r.final_score)
            item = self._serialize(r.result_id, r.rank, c, t, scenes.get(t.scene_id), None)
            item["change_analysis_id"] = r.change_analysis_id
            item["status"] = r.status
            out.append(item)
        return {"query_id": sq.query_id, "query_type": sq.query_type, "query": sq.query_text,
                "filters": sq.filters_json, "parsed_query": sq.parsed_json, "embedding_model": sq.embedding_model,
                "created_at": sq.created_at, "total": len(out), "results": out}

