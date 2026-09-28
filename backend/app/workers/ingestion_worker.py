from app.db.session import SessionLocal
from app.services.ingestion.pipeline import IngestionService
from app.workers.jobs import register


@register("ingest_scene")
def ingest_scene(params: dict, progress) -> dict:
    with SessionLocal() as db:
        return IngestionService(db, progress).ingest_scene(params["path"], params.get("metadata"),
                                                           params.get("force", False)).to_dict()


@register("ingest_batch")
def ingest_batch(params: dict, progress) -> dict:
    with SessionLocal() as db:
        return IngestionService(db, progress).ingest_batch(params["paths"], params.get("metadata"),
                                                           params.get("force", False))


@register("ingest_incremental")
def ingest_incremental(params: dict, progress) -> dict:
    with SessionLocal() as db:
        return IngestionService(db, progress).ingest_incremental(params.get("directories"), params.get("metadata"))
