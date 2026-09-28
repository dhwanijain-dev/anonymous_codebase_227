from datetime import datetime

from sqlalchemy import select

from app.db.models import TemporalObservation, Tile
from app.repositories.base import Repository
from app.vector.metadata_filter import bbox_condition


class TileRepository(Repository):
    def get(self, tile_id: str) -> Tile | None:
        return self.db.scalar(select(Tile).where(Tile.tile_id == tile_id))

    def get_many(self, tile_ids: list[str]) -> dict[str, Tile]:
        out = {}
        for s in range(0, len(tile_ids), 900):
            out.update({t.tile_id: t for t in self.db.scalars(select(Tile).where(Tile.tile_id.in_(tile_ids[s:s + 900])))})
        return out

    def for_scene(self, scene_id: str, limit: int = 1000, offset: int = 0) -> list[Tile]:
        return list(self.db.scalars(select(Tile).where(Tile.scene_id == scene_id)
                                    .order_by(Tile.y_index.desc(), Tile.x_index).limit(limit).offset(offset)))

    def existing_ids(self, scene_id: str) -> set[str]:
        return set(self.db.scalars(select(Tile.tile_id).where(Tile.scene_id == scene_id)))

    def observations(self, bbox: list[float], start: datetime | None, end: datetime | None,
                     location_keys: list[str] | None = None) -> list[tuple[TemporalObservation, Tile]]:
        stmt = select(TemporalObservation, Tile).join(Tile, Tile.tile_id == TemporalObservation.tile_id)
        if bbox:
            stmt = stmt.where(bbox_condition(TemporalObservation, bbox, self.dialect, "location"))
        if start:
            stmt = stmt.where(TemporalObservation.acquisition_time >= start)
        if end:
            stmt = stmt.where(TemporalObservation.acquisition_time <= end)
        if location_keys:
            stmt = stmt.where(TemporalObservation.location_key.in_(location_keys))
        stmt = stmt.order_by(TemporalObservation.location_key, TemporalObservation.acquisition_time)
        return list(self.db.execute(stmt).tuples())
