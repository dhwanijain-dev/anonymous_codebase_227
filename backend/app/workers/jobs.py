"""Job abstraction with three backends:

* local  - in-process ThreadPoolExecutor, state in the `job` table (default; no Redis)
* sync   - runs inline (tests, CLI scripts)
* celery - optional Celery/Redis; workers call the same registered handlers
"""
from __future__ import annotations

import threading
import traceback
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from typing import Any

from sqlalchemy import select

from app.core.config import get_settings
from app.core.exceptions import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.db.base import utcnow
from app.db.models import Job
from app.db.session import SessionLocal

log = get_logger(__name__)
Handler = Callable[[dict, Callable[[float, str], None]], dict]
HANDLERS: dict[str, Handler] = {}


def register(job_type: str):
    def deco(fn: Handler) -> Handler:
        HANDLERS[job_type] = fn
        return fn
    return deco


def _update(job_id: str, **fields) -> None:
    with SessionLocal() as db:
        job = db.scalar(select(Job).where(Job.job_id == job_id))
        if job:
            for k, v in fields.items():
                setattr(job, k, v)
            db.commit()


def execute(job_id: str) -> None:
    """Run a job by id (used by every backend)."""
    from app.workers import load_handlers

    load_handlers()
    with SessionLocal() as db:
        job = db.scalar(select(Job).where(Job.job_id == job_id))
        if job is None or job.status == "cancelled":
            return
        job_type, params = job.job_type, dict(job.params_json)
    _update(job_id, status="running", started_at=utcnow(), progress=0.0)

    def progress(p: float, msg: str = "") -> None:
        _update(job_id, progress=round(float(p), 4), result_json={"message": msg})

    try:
        result = HANDLERS[job_type](params, progress)
        _update(job_id, status="succeeded", progress=1.0, result_json=result, finished_at=utcnow())
    except Exception as e:
        log.exception(f"job {job_id} failed")
        _update(job_id, status="failed", error=f"{e}\n{traceback.format_exc(limit=5)}"[:4000], finished_at=utcnow())


class JobBackend:
    def submit(self, job_id: str) -> None:
        raise NotImplementedError


class SyncJobBackend(JobBackend):
    def submit(self, job_id):
        execute(job_id)


class LocalJobBackend(JobBackend):
    def __init__(self, workers: int):
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="eo-job")

    def submit(self, job_id):
        self.pool.submit(execute, job_id)


class CeleryJobBackend(JobBackend):
    def submit(self, job_id):
        from app.workers.celery_app import run_job

        run_job.delay(job_id)


class JobManager:
    def __init__(self, backend: JobBackend):
        self.backend = backend
        self._lock = threading.Lock()

    def submit(self, job_type: str, params: dict[str, Any]) -> dict:
        from app.workers import load_handlers

        load_handlers()
        if job_type not in HANDLERS:
            raise ValidationError(f"Unknown job type {job_type}", {"available": sorted(HANDLERS)})
        job_id = f"job_{uuid.uuid4().hex[:20]}"
        with SessionLocal() as db:
            db.add(Job(job_id=job_id, job_type=job_type, params_json=params, status="queued"))
            db.commit()
        self.backend.submit(job_id)
        return self.get(job_id)

    def get(self, job_id: str) -> dict:
        with SessionLocal() as db:
            j = db.scalar(select(Job).where(Job.job_id == job_id))
            if j is None:
                raise NotFoundError(f"Job '{job_id}' not found")
            return serialize(j)

    def list(self, status: str | None = None, job_type: str | None = None, limit: int = 50) -> list[dict]:
        with SessionLocal() as db:
            stmt = select(Job).order_by(Job.created_at.desc()).limit(limit)
            if status:
                stmt = stmt.where(Job.status == status)
            if job_type:
                stmt = stmt.where(Job.job_type == job_type)
            return [serialize(j) for j in db.scalars(stmt)]

    def cancel(self, job_id: str) -> dict:
        with SessionLocal() as db:
            j = db.scalar(select(Job).where(Job.job_id == job_id))
            if j is None:
                raise NotFoundError(f"Job '{job_id}' not found")
            if j.status == "queued":
                j.status, j.finished_at = "cancelled", utcnow()
                db.commit()
        return self.get(job_id)

    @staticmethod
    def recover_interrupted() -> int:
        """Jobs left 'running' by a crashed process are marked failed (ingestion is resumable)."""
        with SessionLocal() as db:
            rows = list(db.scalars(select(Job).where(Job.status.in_(["running", "queued"]))))
            for j in rows:
                j.status, j.error, j.finished_at = "failed", "interrupted by restart; resubmit to resume", utcnow()
            db.commit()
            return len(rows)


def serialize(j: Job) -> dict:
    return {"job_id": j.job_id, "job_type": j.job_type, "status": j.status, "progress": j.progress,
            "params": j.params_json, "result": j.result_json, "error": j.error, "created_at": j.created_at,
            "started_at": j.started_at, "finished_at": j.finished_at}


@lru_cache
def get_job_manager() -> JobManager:
    s = get_settings()
    backend = {"sync": lambda: SyncJobBackend(), "celery": lambda: CeleryJobBackend()}.get(
        s.JOB_BACKEND, lambda: LocalJobBackend(s.JOB_WORKERS))()
    return JobManager(backend)
