"""Analyst review + feedback capture. No automatic retraining: feedback is stored for
reranking, hard-negative mining, evaluation and future fine-tuning."""
from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, ValidationError
from app.db.models import AnalystReview, ChangeAnalysis, SearchQuery, SearchResult, Tile
from app.geo import raster
from app.repositories.review_repository import ReviewRepository

DECISIONS = ("accept", "reject", "uncertain")
STATUS_FOR = {"accept": "accepted", "reject": "rejected", "uncertain": "uncertain"}


class ReviewService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = ReviewRepository(db)

    def submit(self, result_id: str, decision: str, comment: str | None, analyst_id: str,
               query_id: str | None = None) -> dict:
        if decision not in DECISIONS:
            raise ValidationError(f"decision must be one of {DECISIONS}")
        sr = self.db.scalar(select(SearchResult).where(SearchResult.result_id == result_id))
        ca = None if sr else self.db.scalar(select(ChangeAnalysis).where(ChangeAnalysis.analysis_id == result_id))
        if sr is None and ca is None:
            raise NotFoundError(f"No search result or change analysis '{result_id}'")
        if sr and query_id and sr.query_id != query_id:
            raise ValidationError("result_id does not belong to query_id")
        target = sr or ca
        ctx = ({"tile_id": sr.tile_id, "rank": sr.rank, "final_score": sr.final_score,
                "semantic_score": sr.semantic_score, "change_score": sr.change_score,
                "change_analysis_id": sr.change_analysis_id} if sr else
               {"change_type": ca.change_type, "confidence": ca.confidence, "model": f"{ca.model_name}@{ca.model_version}"})
        rev = self.repo.add(AnalystReview(
            review_id=f"rev_{uuid.uuid4().hex[:20]}", query_id=sr.query_id if sr else query_id,
            result_id=result_id, result_type="search_result" if sr else "change_analysis",
            decision=decision, comment=comment, analyst_id=analyst_id or "anonymous", context_json=ctx))
        target.status = STATUS_FOR[decision]  # latest decision wins; history is kept
        # propagate to the linked change analysis so the change queue reflects it too
        if sr and sr.change_analysis_id:
            linked = self.db.scalar(select(ChangeAnalysis).where(ChangeAnalysis.analysis_id == sr.change_analysis_id))
            if linked:
                linked.status = STATUS_FOR[decision]
        self.db.commit()
        return self.serialize(rev)

    @staticmethod
    def serialize(r: AnalystReview) -> dict:
        return {"review_id": r.review_id, "query_id": r.query_id, "result_id": r.result_id,
                "result_type": r.result_type, "decision": r.decision, "comment": r.comment,
                "analyst_id": r.analyst_id, "timestamp": r.timestamp, "context": r.context_json}

    def queue(self, *, min_confidence: float | None = None, max_confidence: float | None = None,
              date_from: datetime | None = None, date_to: datetime | None = None, sensor: str | None = None,
              status: str = "pending_review", change_type: str | None = None, item_type: str | None = None,
              limit: int = 50, offset: int = 0) -> dict:
        items = []
        if item_type in (None, "change_analysis"):
            stmt = select(ChangeAnalysis)
            if status != "all":
                stmt = stmt.where(ChangeAnalysis.status == status)
            if change_type:
                stmt = stmt.where(ChangeAnalysis.change_type == change_type)
            if min_confidence is not None:
                stmt = stmt.where(ChangeAnalysis.confidence >= min_confidence)
            if max_confidence is not None:
                stmt = stmt.where(ChangeAnalysis.confidence <= max_confidence)
            if date_from:
                stmt = stmt.where(ChangeAnalysis.earliest_supported_time >= date_from)
            if date_to:
                stmt = stmt.where(ChangeAnalysis.earliest_supported_time <= date_to)
            for ca in self.db.scalars(stmt.limit(limit + offset)):
                if sensor:
                    tiles = {e.after_tile_id for e in ca.evidence}
                    sens = set(self.db.scalars(select(Tile.sensor).where(Tile.tile_id.in_(tiles))))
                    if sensor.lower() not in {(s or "").lower() for s in sens}:
                        continue
                items.append({"item_type": "change_analysis", "id": ca.analysis_id, "confidence": ca.confidence,
                              "change_type": ca.change_type, "status": ca.status,
                              "time": ca.earliest_supported_time, "geometry": raster.geojson(ca.geometry),
                              "created_at": ca.created_at})
        if item_type in (None, "search_result") and not change_type:
            stmt = select(SearchResult, Tile).join(Tile, Tile.tile_id == SearchResult.tile_id)
            if status != "all":
                stmt = stmt.where(SearchResult.status == status)
            if min_confidence is not None:
                stmt = stmt.where(SearchResult.final_score >= min_confidence)
            if max_confidence is not None:
                stmt = stmt.where(SearchResult.final_score <= max_confidence)
            if date_from:
                stmt = stmt.where(Tile.acquisition_time >= date_from)
            if date_to:
                stmt = stmt.where(Tile.acquisition_time <= date_to)
            if sensor:
                stmt = stmt.where(func.lower(Tile.sensor) == sensor.lower())
            for sr, t in self.db.execute(stmt.limit(limit + offset)).tuples():
                items.append({"item_type": "search_result", "id": sr.result_id, "query_id": sr.query_id,
                              "confidence": sr.final_score, "change_type": None, "status": sr.status,
                              "tile_id": t.tile_id, "sensor": t.sensor, "time": t.acquisition_time,
                              "geometry": raster.geojson(t.geometry)})
        # most informative first: uncertain-ish scores near the decision boundary rank higher
        items.sort(key=lambda i: (abs((i["confidence"] or 0) - 0.5), str(i["id"])))
        return {"total": len(items), "items": items[offset: offset + limit]}

    def history(self, **kw) -> dict:
        rows, total = self.repo.history(**kw)
        return {"total": total, "items": [self.serialize(r) for r in rows]}


class FeedbackService:
    def __init__(self, db: Session):
        self.db = db

    def _latest(self) -> list[AnalystReview]:
        rows = list(self.db.scalars(select(AnalystReview).order_by(AnalystReview.timestamp, AnalystReview.id)))
        latest: dict[str, AnalystReview] = {}
        for r in rows:
            latest[r.result_id] = r
        return list(latest.values())

    def statistics(self) -> dict:
        all_rows = list(self.db.scalars(select(AnalystReview)))
        latest = self._latest()
        by_dec = Counter(r.decision for r in latest)
        by_type = defaultdict(Counter)
        buckets = defaultdict(Counter)
        for r in latest:
            ctx = r.context_json or {}
            if r.result_type == "change_analysis":
                by_type[ctx.get("change_type", "unknown")][r.decision] += 1
                score = ctx.get("confidence")
            else:
                score = ctx.get("final_score")
            if score is not None:
                b = min(int(score * 10), 9) / 10
                buckets[f"{b:.1f}-{b + 0.1:.1f}"][r.decision] += 1
        prec = lambda c: round(c["accept"] / (c["accept"] + c["reject"]), 4) if (c["accept"] + c["reject"]) else None  # noqa: E731
        conflicting = sum(1 for rid, n in Counter(r.result_id for r in all_rows).items()
                          if n > 1 and len({x.decision for x in all_rows if x.result_id == rid}) > 1)
        return {
            "total_reviews": len(all_rows), "reviewed_items": len(latest),
            "decisions": dict(by_dec), "precision": prec(by_dec),
            "by_change_type": {k: dict(v) | {"precision": prec(v)} for k, v in by_type.items()},
            "calibration": {k: dict(v) | {"precision": prec(v)} for k, v in sorted(buckets.items())},
            "hard_negatives": len(self.hard_negatives(limit=10_000)),
            "items_with_conflicting_reviews": conflicting,
            "analysts": len({r.analyst_id for r in all_rows}),
            "queries_reviewed": len({r.query_id for r in all_rows if r.query_id}),
        }

    def hard_negatives(self, min_score: float = 0.5, limit: int = 1000) -> list[dict]:
        """Rejected results the system scored highly — prime material for reranker / encoder tuning."""
        out = []
        for r in self._latest():
            if r.decision != "reject":
                continue
            score = (r.context_json or {}).get("final_score", (r.context_json or {}).get("confidence"))
            if score is not None and score >= min_score:
                sq = self.db.scalar(select(SearchQuery).where(SearchQuery.query_id == r.query_id)) if r.query_id else None
                out.append({"result_id": r.result_id, "result_type": r.result_type, "score": score,
                            "tile_id": (r.context_json or {}).get("tile_id"),
                            "query_text": sq.query_text if sq else None, "comment": r.comment})
        return sorted(out, key=lambda x: -x["score"])[:limit]

    def training_export(self) -> list[dict]:
        """(query, tile, label) triples for offline fine-tuning/evaluation."""
        out = []
        for r in self._latest():
            if r.result_type != "search_result":
                continue
            sq = self.db.scalar(select(SearchQuery).where(SearchQuery.query_id == r.query_id))
            out.append({"query_id": r.query_id, "query_text": sq.query_text if sq else None,
                        "query_type": sq.query_type if sq else None,
                        "tile_id": (r.context_json or {}).get("tile_id"), "label": r.decision,
                        "scores": r.context_json, "embedding_model": sq.embedding_model if sq else None})
        return out
