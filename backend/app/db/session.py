from collections.abc import Iterator

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

_engine = None
_SessionLocal: sessionmaker | None = None


def get_engine():
    global _engine, _SessionLocal
    if _engine is None:
        s = get_settings()
        kwargs = {"pool_pre_ping": True, "future": True}
        if s.is_sqlite:
            kwargs["connect_args"] = {"check_same_thread": False}
        else:
            kwargs.update(pool_size=10, max_overflow=20)
        _engine = create_engine(s.DATABASE_URL, **kwargs)
        if s.is_sqlite:
            @event.listens_for(_engine, "connect")
            def _fk(dbapi_conn, _):
                cur = dbapi_conn.cursor()
                cur.execute("PRAGMA foreign_keys=ON")
                cur.execute("PRAGMA journal_mode=WAL")
                cur.close()
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, autoflush=False)
    return _engine


def reset_engine() -> None:
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine, _SessionLocal = None, None


def SessionLocal() -> Session:
    get_engine()
    return _SessionLocal()


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create extension + tables. Production should prefer `alembic upgrade head`."""
    from app.db import models  # noqa: F401  (register mappers)
    from app.db.base import Base

    engine = get_engine()
    if engine.dialect.name == "postgresql":
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
    Base.metadata.create_all(engine)
    if engine.dialect.name == "postgresql":
        from app.db.models import SPATIAL_INDEX_DDL

        with engine.begin() as conn:
            for ddl in SPATIAL_INDEX_DDL:
                conn.execute(text(ddl))
