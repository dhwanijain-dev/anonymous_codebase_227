from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.api.deps import get_job_manager

router = APIRouter(prefix="/jobs", tags=["jobs"])


class JobSubmit(BaseModel):
    job_type: str
    params: dict = {}


@router.get("")
def list_jobs(status: str | None = None, job_type: str | None = None, limit: int = Query(50, le=500)):
    return {"items": get_job_manager().list(status, job_type, limit)}


@router.post("", summary="Submit a maintenance job (e.g. reconcile_index, rebuild_index)")
def submit_job(req: JobSubmit):
    return get_job_manager().submit(req.job_type, req.params)


@router.get("/{job_id}")
def get_job(job_id: str):
    return get_job_manager().get(job_id)


@router.post("/{job_id}/cancel")
def cancel_job(job_id: str):
    return get_job_manager().cancel(job_id)
