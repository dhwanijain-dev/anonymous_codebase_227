from datetime import datetime

from sqlalchemy import func, select

from app.db.models import Scene
from app.repositories.base import Repository
from app.vector.metadata_filter import bbox_condition


class SceneRepository(Repository):
    def get(self, scene_id: str) -> Scene | None:
        return self.db.scalar(select(Scene).where(Scene.scene_id == scene_id))

    def by_checksum(self, checksum: str) -> Scene | None:
        return self.db.scalar(select(Scene).where(Scene.checksum == checksum))

    def known_paths(self) -> set[str]:
        return set(self.db.scalars(select(Scene.source_path)))

    def add(self, scene: Scene) -> Scene:
        self.db.add(scene)
        self.db.flush()
        return scene

    def list(self, *, sensor: str | None = None, platform: str | None = None, status: str | None = None,
             date_from: datetime | None = None, date_to: datetime | None = None, bbox: list[float] | None = None,
             limit: int = 50, offset: int = 0) -> tuple[list[Scene], int]:
        stmt = select(Scene)
        if sensor:
            stmt = stmt.where(func.lower(Scene.sensor) == sensor.lower())
        if platform:
            stmt = stmt.where(func.lower(Scene.platform) == platform.lower())
        if status:
            stmt = stmt.where(Scene.status == status)
        if date_from:
            stmt = stmt.where(Scene.acquisition_time >= date_from)
        if date_to:
            stmt = stmt.where(Scene.acquisition_time <= date_to)
        if bbox:
            stmt = stmt.where(bbox_condition(Scene, bbox, self.dialect))
        total = self.db.scalar(select(func.count()).select_from(stmt.subquery()))
        rows = self.db.scalars(stmt.order_by(Scene.acquisition_time.desc().nullslast(), Scene.id)
                               .limit(limit).offset(offset)).all()
        return list(rows), int(total or 0)
