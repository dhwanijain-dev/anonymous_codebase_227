import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def init():
    from app.core.config import get_settings
    from app.core.logging import configure_logging
    from app.db.session import SessionLocal, init_db
    from app.services.registry import sync_model_registry

    configure_logging(get_settings().LOG_LEVEL)
    init_db()
    with SessionLocal() as db:
        sync_model_registry(db)
