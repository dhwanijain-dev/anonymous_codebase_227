import json
import uuid
from pathlib import Path

import numpy as np
from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.routes.search import params_from
from app.core.config import get_settings
from app.core.exceptions import ValidationError
from app.core.security import resolve_safe_path
from app.geo import raster
from app.schemas.search import ImageSearchRequest, SearchFilters, SearchResponse
from app.services.retrieval.service import RetrievalService
from app.storage import get_storage

router = APIRouter(prefix="/search", tags=["search"])
MAX_UPLOAD = 200 * 1024 * 1024


def _load_image(path: Path) -> tuple[np.ndarray, np.ndarray]:
    s = get_settings()
    if path.suffix.lower() in raster.SUPPORTED_EXT:
        arr, meta = raster.read_raster(path)
        valid = raster.valid_mask(arr, meta["nodata"])
        scale = raster.reflectance_scale(meta["dtype"], float(arr.max()) if arr.size else 1, s.REFLECTANCE_SCALE)
        return raster.normalize(arr, valid, scale), valid
    from PIL import Image

    img = np.asarray(Image.open(path).convert("RGB"), dtype=np.float32) / 255.0
    # RGB image -> band order expected by BAND_MAPPING (blue, green, red, [nir≈green])
    m = s.BAND_MAPPING
    n = max(m.values())
    arr = np.zeros((n, *img.shape[:2]), np.float32)
    for role, ch in (("red", 0), ("green", 1), ("blue", 2)):
        if role in m:
            arr[m[role] - 1] = img[..., ch]
    if "nir" in m:
        arr[m["nir"] - 1] = img[..., 1]
    return arr, arr.max(axis=0) > 0


@router.post("/image", response_model=SearchResponse, summary="Image-to-image search by local path (JSON)")
def search_image(req: ImageSearchRequest, db: Session = Depends(get_db)):
    p = resolve_safe_path(req.image_path)
    if not p.exists():
        raise ValidationError(f"Image not found: {p}")
    img, valid = _load_image(p)
    return RetrievalService(db).search_image(img, valid, params_from(req), str(p))


@router.post("/image/upload", response_model=SearchResponse,
             summary="Image-to-image search by upload (multipart); filters as JSON string")
async def search_image_upload(file: UploadFile = File(...), filters: str = Form("{}"),
                              db: Session = Depends(get_db)):
    data = await file.read()
    if len(data) > MAX_UPLOAD:
        raise ValidationError("Upload too large")
    suffix = Path(file.filename or "upload.tif").suffix.lower() or ".tif"
    if suffix not in raster.SUPPORTED_EXT | {".png", ".jpg", ".jpeg"}:
        raise ValidationError(f"Unsupported upload type {suffix}")
    key = f"uploads/{uuid.uuid4().hex}{suffix}"
    get_storage().save(key, data)
    f = SearchFilters(**json.loads(filters or "{}"))
    img, valid = _load_image(get_storage().get_path(key))
    return RetrievalService(db).search_image(img, valid, params_from(f), f"upload:{file.filename}")
