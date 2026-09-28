from datetime import datetime
from typing import Any

from app.schemas.common import ORMModel


class TileOut(ORMModel):
    tile_id: str
    scene_id: str
    geometry: Any = None  # WKT from ORM -> GeoJSON in the route
    bbox: list[float] | None
    x_index: int
    y_index: int
    width: int
    height: int
    location_key: str | None
    acquisition_time: datetime | None
    sensor: str | None
    platform: str | None
    raster_path: str
    thumbnail_path: str | None
    mask_path: str | None
    quality_score: float | None
    cloud_percentage: float | None
    valid_pixel_percentage: float | None
    quality_json: dict[str, Any] = {}
    created_at: datetime
