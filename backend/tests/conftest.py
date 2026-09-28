import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _reset():
    from app.core.config import get_settings
    from app.db.session import reset_engine
    from app.services.registry import reset_registry
    from app.storage import get_storage
    from app.workers.jobs import get_job_manager

    get_settings.cache_clear()
    get_storage.cache_clear()
    get_job_manager.cache_clear()
    reset_registry()
    reset_engine()


@pytest.fixture(scope="session")
def env(tmp_path_factory):
    root = tmp_path_factory.mktemp("eo")
    os.environ.update({
        "DATA_ROOT": str(root / "data"), "DATABASE_URL": os.environ.get("TEST_DATABASE_URL", f"sqlite:///{root / 'eo.db'}"), "JOB_BACKEND": "sync",
        "EMBEDDING_BACKEND": "mock", "LOG_LEVEL": "WARNING", "API_KEYS": "[]",
    })
    _reset()
    if not os.environ["DATABASE_URL"].startswith("sqlite"):
        # fresh schema per run on PostgreSQL/PostGIS
        from sqlalchemy import text

        from app.db.session import get_engine
        with get_engine().begin() as c:
            c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    from tests.synth import build_series

    paths = build_series(root / "data" / "raw")
    yield {"root": root, "paths": paths}
    _reset()


@pytest.fixture(scope="session")
def client(env):
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c


@pytest.fixture(scope="session")
def ingested(client, env):
    r = client.post("/api/v1/ingestion/batch", json={"paths": [str(p) for p in env["paths"].values()],
                                                     "background": False})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["failed"] == 0, body["errors"]
    return body
