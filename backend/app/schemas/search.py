from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.schemas.common import BBoxModel, ProvenanceRef


class SearchFilters(BBoxModel):
    top_k: int = Field(20, ge=1, le=500)
    date_from: datetime | None = None
    date_to: datetime | None = None
    sensor: str | None = None
    platform: str | None = None
    min_quality: float | None = Field(None, ge=0, le=1)
    max_cloud: float | None = Field(None, ge=0, le=100)
    require_change: bool = False
    change_types: list[str] | None = None
    group_by_location: bool = True

    @model_validator(mode="after")
    def _dates(self):
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from must be <= date_to")
        return self


class TextSearchRequest(SearchFilters):
    query: str = Field(min_length=1, max_length=1000, examples=["newly built structures near a river"])


class ImageSearchRequest(SearchFilters):
    image_path: str = Field(description="Local GeoTIFF/PNG path inside allowed roots")


class ChangeRef(BaseModel):
    analysis_id: str | None
    change_type: str
    confidence: float
    earliest_supported_time: datetime | None


class SearchResultOut(BaseModel):
    result_id: str
    rank: int
    tile_id: str
    scene_id: str
    geometry: dict | None
    bbox: list[float] | None
    location_key: str | None
    acquisition_time: datetime | None
    sensor: str | None
    platform: str | None
    semantic_score: float
    quality_score: float
    metadata_score: float
    spatial_score: float | None = None
    temporal_score: float | None = None
    change_score: float
    final_score: float
    confidence: float
    change: ChangeRef | None = None
    change_analysis_id: str | None = None
    status: str | None = None
    thumbnail_url: str
    thumbnail_path: str | None
    provenance: ProvenanceRef


class SearchResponse(BaseModel):
    query_id: str
    query_type: str
    query: str | None
    parsed_query: dict[str, Any] | None = None
    total: int
    results: list[SearchResultOut]
    stats: dict[str, Any] = {}
    embedding_model: Any = None
    filters: dict[str, Any] | None = None
    created_at: datetime | None = None
