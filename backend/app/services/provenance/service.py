"""Provenance: every entity records how it was produced; lookups walk the lineage graph
(search_result -> tile -> scene, change_analysis -> tiles -> scenes) back to source files."""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.db.models import ChangeAnalysis, ProvenanceRecord, Scene, SearchQuery, SearchResult, Tile
from app.repositories.provenance_repository import ProvenanceRepository

ENTITY_TYPES = {"scene", "tile", "embedding", "search_query", "search_result", "change_analysis"}


class ProvenanceService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = ProvenanceRepository(db)

    def record(self, entity_type: str, entity_id: str, step: str, *, scene: Scene | None = None,
               parent: str | None = None, **fields: Any) -> ProvenanceRecord:
        rec = ProvenanceRecord(
            entity_type=entity_type, entity_id=entity_id, processing_step=step, parent_entity=parent,
            source_scene_id=scene.scene_id if scene else fields.pop("source_scene_id", None),
            source_path=scene.source_path if scene else fields.pop("source_path", None),
            source_checksum=scene.checksum if scene else fields.pop("source_checksum", None),
            preprocessing_version=fields.pop("preprocessing_version", None),
            embedding_model=fields.pop("embedding_model", None),
            embedding_version=fields.pop("embedding_version", None),
            change_model=fields.pop("change_model", None),
            change_model_version=fields.pop("change_model_version", None),
            parameters_json=fields.pop("parameters", {}) or {},
        )
        return self.repo.add(rec)

    # ------------------------------------------------------------------ lookup
    def _parents(self, entity_type: str, entity_id: str) -> list[tuple[str, str]]:
        if entity_type == "search_result":
            r = self.db.scalar(select(SearchResult).where(SearchResult.result_id == entity_id))
            if r:
                out = [("tile", r.tile_id), ("search_query", r.query_id)]
                if r.change_analysis_id:
                    out.append(("change_analysis", r.change_analysis_id))
                return out
        if entity_type == "tile":
            t = self.db.scalar(select(Tile).where(Tile.tile_id == entity_id))
            return [("scene", t.scene_id)] if t else []
        if entity_type == "change_analysis":
            ca = self.db.scalar(select(ChangeAnalysis).where(ChangeAnalysis.analysis_id == entity_id))
            if ca:
                tiles = {e.before_tile_id for e in ca.evidence} | {e.after_tile_id for e in ca.evidence}
                return [("tile", t) for t in sorted(tiles)]
        return []

    def _exists(self, entity_type: str, entity_id: str) -> bool:
        model, col = {
            "scene": (Scene, Scene.scene_id), "tile": (Tile, Tile.tile_id),
            "search_query": (SearchQuery, SearchQuery.query_id),
            "search_result": (SearchResult, SearchResult.result_id),
            "change_analysis": (ChangeAnalysis, ChangeAnalysis.analysis_id),
        }.get(entity_type, (None, None))
        if model is None:
            return bool(self.repo.for_entity(entity_type, entity_id))
        return self.db.scalar(select(model.id).where(col == entity_id)) is not None

    def get(self, entity_type: str, entity_id: str) -> dict:
        if entity_type not in ENTITY_TYPES:
            raise NotFoundError(f"Unknown entity type '{entity_type}'", {"allowed": sorted(ENTITY_TYPES)})
        if not self._exists(entity_type, entity_id):
            raise NotFoundError(f"{entity_type} '{entity_id}' not found")

        steps: list[dict] = []
        scenes: dict[str, Scene] = {}
        seen: set[tuple[str, str]] = set()
        frontier = [(entity_type, entity_id)]
        while frontier:
            et, eid = frontier.pop(0)
            if (et, eid) in seen:
                continue
            seen.add((et, eid))
            for r in self.repo.for_entity(et, eid):
                steps.append(self._rec(r))
                if r.source_scene_id and r.source_scene_id not in scenes:
                    sc = self.db.scalar(select(Scene).where(Scene.scene_id == r.source_scene_id))
                    if sc:
                        scenes[sc.scene_id] = sc
            if et == "scene" and eid not in scenes:
                sc = self.db.scalar(select(Scene).where(Scene.scene_id == eid))
                if sc:
                    scenes[eid] = sc
            frontier += self._parents(et, eid)
            if et == "tile":
                # embeddings are recorded against the tile they describe
                for r in self.repo.for_entity("embedding", eid):
                    steps.append(self._rec(r))

        steps.sort(key=lambda s: (s["timestamp"] or "", s["entity_type"]))
        latest = lambda key: next((s[key] for s in reversed(steps) if s.get(key)), None)  # noqa: E731
        return {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "source_scenes": [
                {"scene_id": s.scene_id, "original_file": s.source_path, "filename": s.filename,
                 "checksum": s.checksum, "sensor": s.sensor, "platform": s.platform,
                 "acquisition_time": s.acquisition_time.isoformat() if s.acquisition_time else None,
                 "crs": s.crs, "ingestion_timestamp": s.ingestion_timestamp.isoformat()}
                for s in scenes.values()],
            "preprocessing_version": latest("preprocessing_version"),
            "embedding_model": latest("embedding_model"),
            "embedding_version": latest("embedding_version"),
            "change_model": latest("change_model"),
            "change_model_version": latest("change_model_version"),
            "processing_steps": steps,
            "complete": bool(scenes) and bool(steps),
        }

    @staticmethod
    def _rec(r: ProvenanceRecord) -> dict:
        return {
            "entity_type": r.entity_type, "entity_id": r.entity_id, "step": r.processing_step,
            "source_scene_id": r.source_scene_id, "source_path": r.source_path, "checksum": r.source_checksum,
            "preprocessing_version": r.preprocessing_version, "embedding_model": r.embedding_model,
            "embedding_version": r.embedding_version, "change_model": r.change_model,
            "change_model_version": r.change_model_version, "parameters": r.parameters_json,
            "parent": r.parent_entity, "timestamp": r.created_at.isoformat() if r.created_at else None,
        }

    def compact(self, entity_type: str, entity_id: str) -> dict:
        """Short provenance block embedded in search/export rows."""
        full = self.get(entity_type, entity_id)
        return {k: full[k] for k in ("entity_type", "entity_id", "preprocessing_version", "embedding_model",
                                     "embedding_version", "change_model", "change_model_version")} | {
            "source_scenes": [{k: s[k] for k in ("scene_id", "original_file", "checksum")}
                              for s in full["source_scenes"]],
            "href": f"/api/v1/provenance/{entity_type}/{entity_id}"}
