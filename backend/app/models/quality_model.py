"""Quality engine: per-tile cloud/haze/snow/shadow/radiometry assessment + class mask.

Heuristic implementation first; `BaseQualityModel` lets a trained cloud/shadow
segmenter (e.g. an exported s2cloudless / CloudSEN12 model) replace it."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field

import numpy as np

from app.geo import spectral
from app.models.base import ModelInfo, PluggableModel, config_checksum

# mask classes
MASK_CLEAR, MASK_NODATA, MASK_CLOUD, MASK_SHADOW, MASK_SNOW, MASK_HAZE, MASK_SATURATED = range(7)


@dataclass
class QualityResult:
    cloud_score: float
    haze_score: float
    snow_score: float
    shadow_score: float
    valid_pixel_ratio: float
    registration_quality: float
    radiometric_quality: float
    overall_quality: float
    usable_for_change_detection: bool
    clear_ratio: float = 0.0
    features: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


class BaseQualityModel(PluggableModel, ABC):
    @abstractmethod
    def assess(self, image: np.ndarray, valid: np.ndarray) -> tuple[QualityResult, np.ndarray]:
        """Return summary scores and a uint8 class mask (MASK_* constants)."""


class HeuristicQualityModel(BaseQualityModel):
    def __init__(self, band_mapping: dict[str, int], cloud_bright: float = 0.75,
                 shadow_dark: float = 0.08, min_quality_for_change: float = 0.5,
                 min_valid: float = 0.2):
        self.band_mapping = band_mapping
        self.cloud_bright, self.shadow_dark = cloud_bright, shadow_dark
        self.min_q, self.min_valid = min_quality_for_change, min_valid

    def assess(self, image, valid):
        n_valid = int(valid.sum())
        total = valid.size
        vratio = n_valid / total
        mask = np.full(valid.shape, MASK_NODATA, dtype=np.uint8)
        if n_valid == 0:
            return QualityResult(0, 0, 0, 0, 0.0, 1.0, 0.0, 0.0, False), mask
        b = spectral.band_roles(image, self.band_mapping)
        ix = spectral.indices(b)
        bright, ndvi, ndwi = ix["brightness"], ix["ndvi"], ix["ndwi"]
        vis = np.stack([b["red"], b["green"], b["blue"]])
        whiteness = vis.std(axis=0) / (bright + 1e-6)  # low => spectrally flat (white/grey)

        snow = valid & (bright > 0.45) & (ndwi > 0.2) & (b["blue"] >= b["red"]) & (b["nir"] < bright)
        cloud = valid & ~snow & (bright > self.cloud_bright * 0.6) & (whiteness < 0.12) & (
            (bright > self.cloud_bright) | (b["nir"] > 0.5))
        # haze: bright blue path radiance relative to red, reduced local contrast
        haze = valid & ~cloud & ~snow & (b["blue"] > 0.2) & (b["blue"] > 1.25 * b["red"]) & (whiteness < 0.25)
        shadow = valid & ~cloud & (bright < self.shadow_dark) & (ndwi < 0.1) & (b["nir"] < 0.12)
        saturated = valid & (vis.max(axis=0) >= 0.999)

        mask[valid] = MASK_CLEAR
        mask[haze] = MASK_HAZE
        mask[shadow] = MASK_SHADOW
        mask[snow] = MASK_SNOW
        mask[cloud] = MASK_CLOUD
        mask[saturated] = MASK_SATURATED

        f = lambda m: float(m.sum() / n_valid)  # noqa: E731
        cloud_s, haze_s, snow_s, shadow_s, sat_s = f(cloud), f(haze), f(snow), f(shadow), f(saturated)
        # cloud shadows accompany clouds: dilate the cloud penalty a little
        cloud_s = min(1.0, cloud_s * 1.15)
        dyn = float(np.percentile(bright[valid], 98) - np.percentile(bright[valid], 2))
        # homogeneous scenes (water, forest) are legitimately low-contrast; only near-flat
        # signal (fill values, dead detectors) is penalised
        radiometric = float(np.clip(1.0 - 2.0 * sat_s, 0, 1) * np.clip(dyn / 0.01, 0.5, 1.0))
        clear = mask == MASK_CLEAR
        clear_ratio = float(clear.sum() / total)
        overall = (vratio * (1 - cloud_s) * (1 - 0.6 * haze_s) * (1 - 0.5 * snow_s)
                   * (1 - 0.5 * shadow_s) * radiometric)
        overall = float(np.clip(overall, 0, 1))
        desc = spectral.descriptor(image, valid, self.band_mapping, clear)
        return QualityResult(
            cloud_score=round(cloud_s, 4), haze_score=round(haze_s, 4), snow_score=round(snow_s, 4),
            shadow_score=round(shadow_s, 4), valid_pixel_ratio=round(vratio, 4),
            registration_quality=1.0,  # single-image; pairwise registration assessed in change detection
            radiometric_quality=round(radiometric, 4), overall_quality=round(overall, 4),
            usable_for_change_detection=bool(overall >= self.min_q and vratio >= self.min_valid
                                             and clear_ratio >= self.min_valid),
            clear_ratio=round(clear_ratio, 4), features=spectral.summary(desc),
        ), mask

    def info(self) -> ModelInfo:
        cfg = {"cloud_bright": self.cloud_bright, "shadow_dark": self.shadow_dark, "min_q": self.min_q}
        return ModelInfo("heuristic-quality", "1.0.0", "quality", None, config_checksum(cfg),
                         "internal", "built-in heuristics",
                         {"image": "float32[bands,H,W] reflectance"}, {"mask": "uint8 classes 0-6"})
