from app.db.session import SessionLocal
from app.services.embeddings.index_service import EmbeddingIndexService
from app.workers.jobs import register


@register("reconcile_index")
def reconcile_index(params: dict, progress) -> dict:
    with SessionLocal() as db:
        return EmbeddingIndexService(db).reconcile()


@register("rebuild_index")
def rebuild_index(params: dict, progress) -> dict:
    with SessionLocal() as db:
        return EmbeddingIndexService(db).rebuild()
