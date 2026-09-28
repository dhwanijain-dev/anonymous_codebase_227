from datetime import datetime

from sqlalchemy import func, select

from app.db.models import AnalystReview
from app.repositories.base import Repository


class ReviewRepository(Repository):
    def add(self, review: AnalystReview) -> AnalystReview:
        self.db.add(review)
        self.db.flush()
        return review

    def history(self, *, result_id: str | None = None, query_id: str | None = None, analyst_id: str | None = None,
                decision: str | None = None, date_from: datetime | None = None, date_to: datetime | None = None,
                limit: int = 100, offset: int = 0) -> tuple[list[AnalystReview], int]:
        stmt = select(AnalystReview)
        for col, val in ((AnalystReview.result_id, result_id), (AnalystReview.query_id, query_id),
                         (AnalystReview.analyst_id, analyst_id), (AnalystReview.decision, decision)):
            if val:
                stmt = stmt.where(col == val)
        if date_from:
            stmt = stmt.where(AnalystReview.timestamp >= date_from)
        if date_to:
            stmt = stmt.where(AnalystReview.timestamp <= date_to)
        total = self.db.scalar(select(func.count()).select_from(stmt.subquery()))
        rows = self.db.scalars(stmt.order_by(AnalystReview.timestamp.desc(), AnalystReview.id.desc())
                               .limit(limit).offset(offset))
        return list(rows), int(total or 0)
