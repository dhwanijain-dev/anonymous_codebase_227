from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.config import get_settings
from app.services.registry import get_embedding_model, get_vector_store
from app.storage import get_storage

router = APIRouter(tags=["health"])


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/health/ready")
def ready(db: Session = Depends(get_db)):
    checks = {}
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = {"ok": True, "dialect": db.get_bind().dialect.name}
    except Exception as e:
        checks["database"] = {"ok": False, "error": str(e)}
    try:
        m = get_embedding_model()
        checks["embedding_model"] = {"ok": True, "model": m.info().key, "text": m.supports_text}
        checks["vector_index"] = {"ok": True, "count": get_vector_store(m).count()}
    except Exception as e:
        checks["embedding_model"] = {"ok": False, "error": str(e)}
    try:
        get_storage().save("logs/.ready", b"ok")
        checks["storage"] = {"ok": True, "root": str(get_settings().DATA_ROOT)}
    except Exception as e:
        checks["storage"] = {"ok": False, "error": str(e)}
    ok = all(c["ok"] for c in checks.values())
    return {"status": "ready" if ok else "degraded", "checks": checks}
