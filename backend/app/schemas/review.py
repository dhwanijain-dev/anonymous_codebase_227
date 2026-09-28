from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ReviewRequest(BaseModel):
    query_id: str | None = None
    result_id: str = Field(description="Search result_id or change analysis_id")
    decision: Literal["accept", "reject", "uncertain"]
    comment: str | None = Field(None, max_length=4000)
    analyst_id: str | None = None


class ReviewOut(BaseModel):
    review_id: str
    query_id: str | None
    result_id: str
    result_type: str
    decision: str
    comment: str | None
    analyst_id: str
    timestamp: datetime
    context: dict[str, Any] = {}
