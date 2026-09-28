from typing import Any

from pydantic import BaseModel


class SourceScene(BaseModel):
    scene_id: str
    original_file: str
    filename: str | None = None
    checksum: str
    sensor: str | None = None
    platform: str | None = None
    acquisition_time: str | None = None
    crs: str | None = None
    ingestion_timestamp: str | None = None


class ProvenanceOut(BaseModel):
    entity_type: str
    entity_id: str
    source_scenes: list[SourceScene]
    preprocessing_version: str | None
    embedding_model: str | None
    embedding_version: str | None
    change_model: str | None
    change_model_version: str | None
    processing_steps: list[dict[str, Any]]
    complete: bool
