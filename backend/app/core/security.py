"""API-key auth (optional) and filesystem path sandboxing for ingestion."""
from pathlib import Path

from fastapi import Header, HTTPException, status

from app.core.config import get_settings
from app.core.exceptions import ForbiddenPathError


def require_api_key(x_api_key: str | None = Header(default=None)) -> str | None:
    keys = get_settings().API_KEYS
    if not keys:
        return None  # auth disabled for local deployment
    if x_api_key not in keys:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or missing X-API-Key")
    return x_api_key


def resolve_safe_path(path: str) -> Path:
    """Only allow reading files inside DATA_ROOT or explicitly allowed roots."""
    s = get_settings()
    p = Path(path).expanduser().resolve()
    roots = [Path(s.DATA_ROOT).resolve()] + [Path(r).resolve() for r in s.ALLOWED_INGEST_ROOTS]
    if not any(p == r or r in p.parents for r in roots):
        raise ForbiddenPathError(f"Path outside allowed roots: {p}", {"roots": [str(r) for r in roots]})
    return p
