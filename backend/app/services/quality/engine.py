"""QualityEngine: the spec's `assess(tile) -> QualityResult` facade over the pluggable
quality model. Accepts a Tile row, a raster path, or an in-memory array."""
from __future__ import annotations

from pathlib import Path

import numpy as np

from app.core.config import get_settings
from app.db.models import Tile
from app.geo import raster
from app.models.quality_model import BaseQualityModel, QualityResult
from app.services.registry import get_quality_model
from app.storage import get_storage


class QualityEngine:
    def __init__(self, model: BaseQualityModel | None = None):
        self.model = model or get_quality_model()

    def assess(self, tile: Tile | str | Path | np.ndarray, valid: np.ndarray | None = None) -> QualityResult:
        return self.assess_with_mask(tile, valid)[0]

    def assess_with_mask(self, tile, valid=None) -> tuple[QualityResult, np.ndarray]:
        if isinstance(tile, np.ndarray):
            img = tile
            valid = valid if valid is not None else img.max(axis=0) > 0
            return self.model.assess(img, valid)
        path = get_storage().get_path(tile.raster_path) if isinstance(tile, Tile) else Path(tile)
        arr, meta = raster.read_raster(path)
        v = raster.valid_mask(arr, meta["nodata"])
        scale = raster.reflectance_scale(meta["dtype"], float(arr.max()) if arr.size else 1.0,
                                         get_settings().REFLECTANCE_SCALE)
        return self.model.assess(raster.normalize(arr, v, scale), v)

    @staticmethod
    def usable_for_change(result: QualityResult, min_quality: float) -> bool:
        return result.usable_for_change_detection and result.overall_quality >= min_quality
