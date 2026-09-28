from sqlalchemy import select

from app.db.models import ProvenanceRecord
from app.repositories.base import Repository


class ProvenanceRepository(Repository):
    def add(self, rec: ProvenanceRecord) -> ProvenanceRecord:
        self.db.add(rec)
        return rec

    def for_entity(self, entity_type: str, entity_id: str) -> list[ProvenanceRecord]:
        return list(self.db.scalars(select(ProvenanceRecord).where(
            ProvenanceRecord.entity_type == entity_type, ProvenanceRecord.entity_id == entity_id)
            .order_by(ProvenanceRecord.created_at, ProvenanceRecord.id)))

    def exists(self, entity_type: str, entity_id: str, step: str) -> bool:
        return self.db.scalar(select(ProvenanceRecord.id).where(
            ProvenanceRecord.entity_type == entity_type, ProvenanceRecord.entity_id == entity_id,
            ProvenanceRecord.processing_step == step).limit(1)) is not None
