from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

BBox = list[float]


def check_bbox(v):
    if v is None:
        return v
    if len(v) != 4:
        raise ValueError("bbox must be [min_lon, min_lat, max_lon, max_lat]")
    minx, miny, maxx, maxy = v
    if not (-180 <= minx <= maxx <= 180 and -90 <= miny <= maxy <= 90):
        raise ValueError("bbox out of range or inverted (EPSG:4326 lon/lat expected)")
    return v


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel):
    total: int
    items: list[Any]


class ProvenanceRef(BaseModel):
    href: str
    source_scene_id: str | None = None
    source_path: str | None = None
    checksum: str | None = None
    embedding_model: str | None = None
    embedding_version: str | None = None
    preprocessing_version: str | None = None


class BBoxModel(BaseModel):
    bbox: BBox | None = Field(default=None, examples=[[77.5, 12.9, 77.7, 13.1]])

    @field_validator("bbox")
    @classmethod
    def _bbox(cls, v):
        return check_bbox(v)


class TimeRange(BaseModel):
    date_from: datetime | None = None
    date_to: datetime | None = None
