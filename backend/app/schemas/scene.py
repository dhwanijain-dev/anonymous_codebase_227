from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class IngestMetadata(BaseModel):
    """Optional overrides when the file lacks tags / sidecar."""
    acquisition_time: datetime | None = None
    sensor: str | None = None
    platform: str | None = None
    processing_level: str | None = None


class IngestSceneRequest(BaseModel):
    path: str = Field(examples=["/data/raw/S2A_MSIL2A_20230115T050000_T43PGQ.tif"])
    metadata: IngestMetadata | None = None
    force: bool = Field(False, description="Re-process even if already complete (vectors still not duplicated)")
    background: bool = Field(False, description="Run as a background job and return the job")


class IngestBatchRequest(BaseModel):
    paths: list[str] = Field(min_length=1)
    metadata: IngestMetadata | None = None
    force: bool = False
    background: bool = True


class IngestIncrementalRequest(BaseModel):
    directories: list[str] | None = Field(None, description="Relative to DATA_ROOT or absolute (allowed roots only)")
    metadata: IngestMetadata | None = None
    background: bool = True


class IngestResponse(BaseModel):
    scene_id: str
    status: str
    created: bool
    duplicate: bool
    tiles_created: int = 0
    tiles_skipped: int = 0
    embeddings_added: int = 0
    message: str = ""
    warnings: list[str] = []


class SceneOut(ORMModel):
    scene_id: str
    source_path: str
    filename: str
    sensor: str | None
    platform: str | None
    acquisition_time: datetime | None
    processing_level: str | None
    crs: str | None
    resolution: float | None
    width: int
    height: int
    bands: int
    geometry: Any = None  # WKT from ORM -> GeoJSON in the route
    bbox: list[float] | None
    cloud_percentage: float | None
    quality_score: float | None
    checksum: str
    ingestion_timestamp: datetime
    status: str
    metadata_json: dict[str, Any] = {}
    tile_count: int | None = None
