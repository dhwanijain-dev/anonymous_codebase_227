from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_api_key
from app.schemas.review import ReviewOut, ReviewRequest
from app.services.feedback.service import FeedbackService, ReviewService

router = APIRouter(tags=["review"])


@router.post("/review", response_model=ReviewOut)
def submit_review(req: ReviewRequest, db: Session = Depends(get_db), api_key: str | None = Depends(require_api_key)):
    analyst = req.analyst_id or (f"key:{api_key[:6]}" if api_key else "anonymous")
    return ReviewService(db).submit(req.result_id, req.decision, req.comment, analyst, req.query_id)


@router.get("/review/queue")
def review_queue(min_confidence: float | None = None, max_confidence: float | None = None,
                 date_from: datetime | None = None, date_to: datetime | None = None, sensor: str | None = None,
                 status: str = "pending_review", change_type: str | None = None,
                 item_type: Literal["change_analysis", "search_result"] | None = None,
                 limit: int = Query(50, le=500), offset: int = 0, db: Session = Depends(get_db)):
    return ReviewService(db).queue(min_confidence=min_confidence, max_confidence=max_confidence,
                                   date_from=date_from, date_to=date_to, sensor=sensor, status=status,
                                   change_type=change_type, item_type=item_type, limit=limit, offset=offset)


@router.get("/review/history")
def review_history(result_id: str | None = None, query_id: str | None = None, analyst_id: str | None = None,
                   decision: str | None = None, date_from: datetime | None = None, date_to: datetime | None = None,
                   limit: int = Query(100, le=1000), offset: int = 0, db: Session = Depends(get_db)):
    return ReviewService(db).history(result_id=result_id, query_id=query_id, analyst_id=analyst_id,
                                     decision=decision, date_from=date_from, date_to=date_to, limit=limit,
                                     offset=offset)


@router.get("/feedback/statistics", tags=["feedback"])
def feedback_statistics(db: Session = Depends(get_db)):
    return FeedbackService(db).statistics()


@router.get("/feedback/hard-negatives", tags=["feedback"])
def hard_negatives(min_score: float = 0.5, limit: int = Query(200, le=10000), db: Session = Depends(get_db)):
    return {"items": FeedbackService(db).hard_negatives(min_score, limit)}


@router.get("/feedback/export", tags=["feedback"], summary="Labelled (query, tile, decision) triples for offline training")
def feedback_export(db: Session = Depends(get_db)):
    return {"items": FeedbackService(db).training_export()}
