from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_job_manager
from app.schemas.scene import IngestBatchRequest, IngestIncrementalRequest, IngestResponse, IngestSceneRequest
from app.services.ingestion.pipeline import IngestionService

router = APIRouter(prefix="/ingestion", tags=["ingestion"])


def _meta(m):
    return m.model_dump(mode="json", exclude_none=True) if m else None


@router.post("/scene", response_model=IngestResponse | dict,
             summary="Ingest one local GeoTIFF/COG (idempotent: duplicates return the existing scene)")
def ingest_scene(req: IngestSceneRequest, db: Session = Depends(get_db)):
    if req.background:
        return get_job_manager().submit("ingest_scene", {"path": req.path, "metadata": _meta(req.metadata),
                                                         "force": req.force})
    return IngestionService(db).ingest_scene(req.path, _meta(req.metadata), req.force).to_dict()


@router.post("/batch", summary="Ingest many files (background job by default)")
def ingest_batch(req: IngestBatchRequest, db: Session = Depends(get_db)):
    if req.background:
        return get_job_manager().submit("ingest_batch", {"paths": req.paths, "metadata": _meta(req.metadata),
                                                         "force": req.force})
    return IngestionService(db).ingest_batch(req.paths, _meta(req.metadata), req.force)


@router.post("/incremental", summary="Discover and ingest only new/changed imagery; appends to the index")
def ingest_incremental(req: IngestIncrementalRequest, db: Session = Depends(get_db)):
    if req.background:
        return get_job_manager().submit("ingest_incremental", {"directories": req.directories,
                                                               "metadata": _meta(req.metadata)})
    return IngestionService(db).ingest_incremental(req.directories, _meta(req.metadata))


@router.get("/discover", summary="Dry run: list files incremental ingestion would process")
def discover(directory: list[str] | None = None, db: Session = Depends(get_db)):
    paths = IngestionService(db).discover(directory)
    return {"count": len(paths), "paths": paths}
