"""Optional Celery wiring (JOB_BACKEND=celery). Run: celery -A app.workers.celery_app worker"""
from celery import Celery

from app.core.config import get_settings

s = get_settings()
celery = Celery("eo", broker=s.REDIS_URL, backend=s.REDIS_URL)


@celery.task(name="eo.run_job")
def run_job(job_id: str) -> None:
    from app.workers.jobs import execute

    execute(job_id)
