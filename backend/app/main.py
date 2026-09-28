from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

from app.api.deps import require_api_key
from app.api.routes import (
    changes, discovery, export, health, ingestion, jobs, models, provenance, review, scenes, search, similarity,
)
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.db.session import SessionLocal, init_db

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    configure_logging(s.LOG_LEVEL)
    init_db()
    from app.services.embeddings.index_service import EmbeddingIndexService
    from app.services.registry import sync_model_registry
    from app.workers.jobs import JobManager

    with SessionLocal() as db:
        sync_model_registry(db)
        EmbeddingIndexService(db).reconcile()  # repair index after an unclean shutdown
    n = JobManager.recover_interrupted()
    if n:
        log.warning(f"marked {n} interrupted jobs as failed")
    log.info("startup complete")
    yield


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title=s.APP_NAME, version="1.0.0", lifespan=lifespan,
                  description="On-premises Earth Observation intelligence: semantic + image search, "
                              "multi-temporal change detection, review and full provenance. No external services.")
    register_exception_handlers(app)
    app.include_router(health.router)
    secured = [Depends(require_api_key)]
    for r in (health, ingestion, scenes, search, similarity, changes, discovery, review, provenance, export, jobs,
              models):
        app.include_router(r.router, prefix=s.API_PREFIX, dependencies=secured)
    return app


app = create_app()
