from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.schemas.common import BBoxModel


class ChangeType(str, Enum):
    construction = "construction"
    clearance = "clearance"
    water_extent_change = "water_extent_change"
    road_development = "road_development"
    appearance = "appearance"
    disappearance = "disappearance"
    expansion = "expansion"
    contraction = "contraction"
    unknown = "unknown"


class ChangeAnalyzeRequest(BBoxModel):
    start_date: datetime | None = None
    end_date: datetime | None = None
    change_types: list[ChangeType] | None = None
    min_quality: float | None = Field(None, ge=0, le=1)
    background: bool = False

    @model_validator(mode="after")
    def _need_bbox(self):
        if not self.bbox:
            raise ValueError("bbox is required")
        return self


class EvidenceOut(BaseModel):
    before_scene: str | None
    after_scene: str | None
    before_tile: str
    after_tile: str
    before_time: datetime | None
    after_time: datetime | None
    score: float
    change_type: str | None = None


class ChangeAnalysisOut(BaseModel):
    analysis_id: str | None
    request_id: str | None = None
    change_type: str
    confidence: float
    earliest_supported_time: datetime | None
    last_unchanged_time: datetime | str | None = None
    geometry: dict | None
    location_key: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    quality_score: float | None = None
    status: str | None = None
    model_name: str | None = None
    model_version: str | None = None
    factors: dict[str, Any] = {}
    evidence: list[EvidenceOut]
    provenance: dict[str, Any] | None = None
    created_at: datetime | None = None


class ChangeAnalyzeResponse(BaseModel):
    request_id: str
    # headline = most confident detection (spec's single-object shape); all detections listed too
    analysis_id: str | None = None
    change_type: str | None = None
    confidence: float | None = None
    earliest_supported_time: datetime | None = None
    geometry: dict | None = None
    evidence: list[EvidenceOut] = []
    provenance: dict[str, Any] | None = None
    detections: list[ChangeAnalysisOut]
    diagnostics: dict[str, Any]
    parameters: dict[str, Any]
    model: dict[str, Any]
