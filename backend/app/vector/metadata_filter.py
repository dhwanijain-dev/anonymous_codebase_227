"""Stage-1 metadata/spatial/temporal/quality filtering in PostgreSQL/PostGIS.

The vector index knows nothing about geography; this module turns API filters into
SQL over the `tile` table (ST_Intersects on PostGIS, bbox overlap on SQLite)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Select, and_, func, select
from sqlalchemy.orm import Session

from app.db.models import Embedding, Tile


@dataclass
class TileFilter:
    bbox: list[float] | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    sensor: str | None = None
    platform: str | None = None
    min_quality: float | None = None
    max_cloud: float | None = None
    scene_ids: list[str] | None = None
    exclude_tile_ids: list[str] | None = None

    def is_empty(self) -> bool:
        return not any([self.bbox, self.date_from, self.date_to, self.sensor, self.platform,
                        self.min_quality, self.max_cloud is not None, self.scene_ids])


def bbox_condition(model, bbox: list[float], dialect: str, geom_col: str = "geometry"):
    minx, miny, maxx, maxy = (float(v) for v in bbox)
    cond = and_(model.max_x >= minx, model.min_x <= maxx, model.max_y >= miny, model.min_y <= maxy)
    if dialect == "postgresql":
        env = func.ST_MakeEnvelope(minx, miny, maxx, maxy, 4326)
        cond = and_(cond, func.ST_Intersects(getattr(model, geom_col), env))
    return cond


def apply_tile_filter(stmt: Select, f: TileFilter, dialect: str) -> Select:
    conds = []
    if f.bbox:
        conds.append(bbox_condition(Tile, f.bbox, dialect))
    if f.date_from:
        conds.append(Tile.acquisition_time >= f.date_from)
    if f.date_to:
        conds.append(Tile.acquisition_time <= f.date_to)
    if f.sensor:
        conds.append(func.lower(Tile.sensor) == f.sensor.lower())
    if f.platform:
        conds.append(func.lower(Tile.platform) == f.platform.lower())
    if f.min_quality is not None:
        conds.append(Tile.quality_score >= f.min_quality)
    if f.max_cloud is not None:
        conds.append(Tile.cloud_percentage <= f.max_cloud)
    if f.scene_ids:
        conds.append(Tile.scene_id.in_(f.scene_ids))
    if f.exclude_tile_ids:
        conds.append(Tile.tile_id.not_in(f.exclude_tile_ids))
    return stmt.where(*conds) if conds else stmt


class MetadataFilter:
    def __init__(self, db: Session, model_name: str, model_version: str):
        self.db = db
        self.dialect = db.get_bind().dialect.name
        self.model_name, self.model_version = model_name, model_version

    def _emb_join(self, stmt: Select) -> Select:
        return stmt.join(Embedding, Embedding.tile_id == Tile.tile_id).where(
            Embedding.model_name == self.model_name, Embedding.model_version == self.model_version,
            Embedding.embedding_type == "image")

    def count(self, f: TileFilter) -> int:
        stmt = apply_tile_filter(self._emb_join(select(func.count()).select_from(Tile)), f, self.dialect)
        return int(self.db.execute(stmt).scalar_one())

    def matching_vector_ids(self, f: TileFilter, limit: int) -> list[int]:
        stmt = apply_tile_filter(self._emb_join(select(Embedding.vector_id).select_from(Tile)), f, self.dialect)
        return list(self.db.execute(stmt.limit(limit)).scalars())

    def filter_candidates(self, tile_ids: list[str], f: TileFilter) -> dict[str, Tile]:
        out: dict[str, Tile] = {}
        for s in range(0, len(tile_ids), 900):
            stmt = apply_tile_filter(select(Tile).where(Tile.tile_id.in_(tile_ids[s:s + 900])), f, self.dialect)
            out.update({t.tile_id: t for t in self.db.execute(stmt).scalars()})
        return out
