"""Pairwise change detectors. The temporal engine (services/change_detection) handles
grouping, quality gating, temporal consensus and confidence; detectors only compare
one aligned before/after pair and explain the difference."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np

from app.core.exceptions import ModelLoadError
from app.geo import spectral
from app.models.base import ModelInfo, PluggableModel, config_checksum, load_model_card, path_checksum
from app.models.quality_model import MASK_CLEAR

CHANGE_TYPES = ["construction", "clearance", "water_extent_change", "road_development", "appearance",
                "disappearance", "expansion", "contraction", "unknown"]


@dataclass
class Observation:
    image: np.ndarray  # normalised reflectance (bands, H, W)
    valid: np.ndarray
    mask: np.ndarray  # quality class mask
    time: datetime | None
    sensor: str | None = None
    platform: str | None = None
    quality: float = 1.0
    extra: dict = field(default_factory=dict)

    @property
    def clear(self) -> np.ndarray:
        return self.valid & (self.mask == MASK_CLEAR)


@dataclass
class PairResult:
    score: float  # base change score in [0,1] after pair-level suppression
    raw_score: float  # before suppression
    changed_fraction: float
    change_type: str
    type_scores: dict[str, float]
    factors: dict[str, float]
    changed_mask: np.ndarray | None = None
    diagnostics: dict = field(default_factory=dict)


class BaseChangeDetector(PluggableModel, ABC):
    @abstractmethod
    def compare(self, before: Observation, after: Observation) -> PairResult: ...


# ----------------------------------------------------------------------------- helpers
def phase_correlation(a: np.ndarray, b: np.ndarray) -> tuple[float, float, float]:
    """Sub-image translation between a and b (dy, dx) and peak sharpness (0-1)."""
    a = a - a.mean()
    b = b - b.mean()
    win = np.outer(np.hanning(a.shape[0]), np.hanning(a.shape[1]))
    fa, fb = np.fft.fft2(a * win), np.fft.fft2(b * win)
    r = fa * np.conj(fb)
    r /= np.abs(r) + 1e-9
    c = np.abs(np.fft.ifft2(r))
    peak = np.unravel_index(np.argmax(c), c.shape)
    dy, dx = [p if p <= s // 2 else p - s for p, s in zip(peak, c.shape)]
    sharp = float(c.max() / (c.sum() + 1e-9) * c.size / 50.0)
    return float(dy), float(dx), float(min(1.0, sharp))


def relative_normalize(before: np.ndarray, after: np.ndarray, common: np.ndarray) -> np.ndarray:
    """Per-band gain/offset matching of `after` to `before` fitted on pseudo-invariant pixels
    (the least-changed half of commonly-clear pixels, cf. IR-MAD/PIF normalisation).
    Suppresses illumination / atmospheric / sensor-gain differences without being
    distorted by the genuine change itself."""
    out = after.copy()
    if common.sum() < 32:
        return out
    raw = np.abs(after - before).mean(axis=0)
    inv = common & (raw <= np.percentile(raw[common], 50))
    if inv.sum() < 32:
        inv = common
    for i in range(after.shape[0]):
        a, b = after[i][inv], before[i][inv]
        gain = float(np.clip(b.std() / max(a.std(), 1e-4), 0.5, 2.0))
        out[i] = (after[i] - a.mean()) * gain + b.mean()
    return np.clip(out, 0, 1)


def day_of_year_gap(t1: datetime | None, t2: datetime | None) -> int | None:
    if not t1 or not t2:
        return None
    d = abs(t1.timetuple().tm_yday - t2.timetuple().tm_yday)
    return min(d, 365 - d)


# ----------------------------------------------------------------------------- detectors
class FeatureDifferenceChangeDetector(BaseChangeDetector):
    """Interpretable detector: registration check -> relative radiometric normalisation ->
    spectral-index + structure differences on commonly-clear pixels -> rule-based typing
    -> pair-level false-alarm suppression factors."""

    def __init__(self, band_mapping: dict[str, int], threshold: float = 0.15,
                 seasonal_tolerance_days: int = 45, version: str = "1.0.0"):
        self.band_mapping = band_mapping
        self.threshold = threshold
        self.seasonal_tol = seasonal_tolerance_days
        self.version = version

    def compare(self, before: Observation, after: Observation) -> PairResult:
        common = before.clear & after.clear
        common_frac = float(common.mean())
        factors: dict[str, float] = {}
        diag: dict = {"common_clear_fraction": round(common_frac, 4)}
        if common.sum() < 64:
            return PairResult(0.0, 0.0, 0.0, "unknown", {}, {"coverage_factor": 0.0}, None,
                              {**diag, "reason": "insufficient commonly-clear pixels"})

        # --- registration (on brightness) -------------------------------------------
        bb = spectral.indices(spectral.band_roles(before.image, self.band_mapping))["brightness"]
        ab = spectral.indices(spectral.band_roles(after.image, self.band_mapping))["brightness"]
        dy, dx, sharp = phase_correlation(bb, ab)
        shift = float(np.hypot(dy, dx))
        after_img = after.image
        applied = False
        if 0 < shift <= 8:
            # accept the correction only if it actually reduces the residual on clear pixels;
            # genuine new structures can otherwise create spurious correlation peaks
            s_ab = np.roll(ab, (int(round(dy)), int(round(dx))), axis=(0, 1))
            before_res = np.abs(ab - bb)[common].mean()
            after_res = np.abs(s_ab - bb)[common].mean()
            if after_res < 0.8 * before_res:
                after_img = np.roll(after.image, (int(round(dy)), int(round(dx))), axis=(1, 2))
                ab, applied = s_ab, True
        if applied:
            # corrected integer shift; sub-pixel residual remains -> mild penalty
            reg = float(np.clip(1.0 - 0.03 * shift, 0.7, 1.0))
        elif shift > 8 and sharp > 0.5:
            reg = 0.3  # confident large misregistration we cannot fix
        else:
            reg = 1.0  # no reliable evidence of misregistration
        factors["registration_factor"] = reg
        diag["registration_shift_px"] = [dy, dx]
        diag["registration_peak"] = round(sharp, 3)
        diag["registration_corrected"] = applied

        # --- illumination / radiometric normalisation -------------------------------
        after_n = relative_normalize(before.image, after_img, common)
        illum_gap = abs(float(np.median(bb[common])) - float(np.median(ab[common])))
        factors["illumination_factor"] = float(np.clip(1.0 - max(illum_gap - 0.05, 0) * 1.5, 0.6, 1.0))

        b0 = spectral.band_roles(before.image, self.band_mapping)
        b1 = spectral.band_roles(after_n, self.band_mapping)
        i0, i1 = spectral.indices(b0), spectral.indices(b1)
        g0 = spectral.gradient_magnitude(i0["brightness"])
        g1 = spectral.gradient_magnitude(i1["brightness"])
        d_ndvi = (i1["ndvi"] - i0["ndvi"])
        d_ndwi = (i1["ndwi"] - i0["ndwi"])
        d_bri = (i1["brightness"] - i0["brightness"])
        d_edge = (g1[0] - g0[0])
        spec = np.sqrt(((after_n - before.image) ** 2).mean(axis=0))
        magnitude = np.maximum.reduce([
            np.abs(d_ndvi) / 0.5, np.abs(d_ndwi) / 0.5, np.abs(d_bri) / 0.25, spec / 0.2])
        changed = common & (magnitude > 1.0)
        # remove speckle: require a changed 4-neighbourhood majority
        nb = (changed.astype(np.int8)
              + np.roll(changed, 1, 0) + np.roll(changed, -1, 0)
              + np.roll(changed, 1, 1) + np.roll(changed, -1, 1))
        changed &= nb >= 3
        frac = float(changed.sum() / max(common.sum(), 1))
        mag = float(np.clip(magnitude[changed].mean() / 3.0, 0, 1)) if changed.any() else 0.0
        raw = float(np.clip(np.sqrt(frac / 0.25) * (0.6 + 0.4 * mag), 0, 1)) if frac > 0.002 else 0.0

        # --- typing ------------------------------------------------------------------
        c = changed
        m = lambda x: float(x[c].mean()) if c.any() else 0.0  # noqa: E731
        dv, dw, db, de = m(d_ndvi), m(d_ndwi), m(d_bri), m(d_edge)
        water0 = float((i0["ndwi"][common] > 0.1).mean())
        water1 = float((i1["ndwi"][common] > 0.1).mean())
        built0 = float(((i0["ndvi"] < 0.15) & (i0["ndwi"] < 0) & (i0["brightness"] > 0.15))[common].mean())
        built1 = float(((i1["ndvi"] < 0.15) & (i1["ndwi"] < 0) & (i1["brightness"] > 0.15))[common].mean())
        lin0 = spectral.linearity(g0[1], g0[2], g0[0], common)
        lin1 = spectral.linearity(g1[1], g1[2], g1[0], common)
        ts = {
            "water_extent_change": abs(water1 - water0) * 4 + abs(dw) * 1.5,
            "construction": max(0, -dv) * 1.2 + max(0, de) * 12 + max(0, built1 - built0) * 4,
            "clearance": max(0, -dv) * 2.0 + max(0, db) * 1.0 - max(0, de) * 6,
            "road_development": max(0, lin1 - lin0) * 4 + max(0, built1 - built0) * 1.5,
            "appearance": max(0, db) * 2 + max(0, de) * 5,
            "disappearance": max(0, -db) * 2 + max(0, -de) * 5,
            "expansion": max(0, built1 - built0) * 3,
            "contraction": max(0, built0 - built1) * 3,
        }
        ts = {k: round(float(max(v, 0)), 4) for k, v in ts.items()}
        best = max(ts, key=ts.get) if raw > 0 else "unknown"
        if raw > 0 and ts[best] < 0.1:
            best = "unknown"
        diag.update(d_ndvi=round(dv, 4), d_ndwi=round(dw, 4), d_brightness=round(db, 4),
                    d_edge=round(de, 5), water_before=round(water0, 4), water_after=round(water1, 4),
                    built_before=round(built0, 4), built_after=round(built1, 4),
                    linearity_before=round(lin0, 4), linearity_after=round(lin1, 4))
        if best == "water_extent_change":
            diag["direction"] = "expansion" if water1 > water0 else "contraction"

        # --- seasonal vegetation suppression -----------------------------------------
        # Phenology: NDVI shifts broadly and uniformly, structure (edges) and water unchanged.
        seasonal = 1.0
        veg0 = i0["ndvi"][common] > 0.3
        if best in ("clearance", "unknown", "appearance", "disappearance") and veg0.mean() > 0.3:
            uniform = float(np.std(d_ndvi[common]) < 0.6 * abs(np.mean(d_ndvi[common])) + 0.05)
            structural = abs(de) > 0.01 or abs(built1 - built0) > 0.05
            doy = day_of_year_gap(before.time, after.time)
            off_season = doy is not None and doy > self.seasonal_tol
            if uniform and not structural:
                seasonal = 0.35 if off_season else 0.6
        factors["seasonal_factor"] = seasonal

        # --- sensor / viewing-geometry differences -----------------------------------
        factors["sensor_factor"] = 1.0 if (before.sensor or "") == (after.sensor or "") else 0.85
        vg = 1.0
        on0, on1 = before.extra.get("view_off_nadir"), after.extra.get("view_off_nadir")
        if on0 is not None and on1 is not None:
            vg *= float(np.clip(1 - max(abs(float(on0) - float(on1)) - 5, 0) / 40, 0.6, 1.0))
        se0, se1 = before.extra.get("sun_elevation"), after.extra.get("sun_elevation")
        if se0 is not None and se1 is not None:
            vg *= float(np.clip(1 - max(abs(float(se0) - float(se1)) - 10, 0) / 60, 0.7, 1.0))
        factors["viewing_geometry_factor"] = vg
        factors["coverage_factor"] = float(np.clip(common_frac / 0.5, 0.3, 1.0))

        suppression = (factors["registration_factor"] * factors["illumination_factor"] * seasonal
                       * factors["sensor_factor"] * vg * factors["coverage_factor"])
        score = float(np.clip(raw * suppression, 0, 1))
        return PairResult(round(score, 4), round(raw, 4), round(frac, 4), best, ts,
                          {k: round(v, 4) for k, v in factors.items()}, changed, diag)

    def info(self) -> ModelInfo:
        cfg = {"threshold": self.threshold, "seasonal_tol": self.seasonal_tol}
        return ModelInfo("feature-difference-change", self.version, "change", None, config_checksum(cfg),
                         "internal", "built-in interpretable detector",
                         {"before/after": "float32[bands,H,W] + masks"}, {"score": "0-1", "type": CHANGE_TYPES})


class MockChangeDetector(BaseChangeDetector):
    """Deterministic detector for tests: mean absolute brightness difference."""

    def compare(self, before, after):
        common = before.clear & after.clear
        if common.sum() == 0:
            return PairResult(0, 0, 0, "unknown", {}, {}, None, {})
        d = np.abs(after.image.mean(0) - before.image.mean(0))
        changed = common & (d > 0.1)
        frac = float(changed.sum() / common.sum())
        s = round(min(1.0, frac * 2), 4)
        t = "appearance" if after.image.mean() > before.image.mean() else "disappearance"
        return PairResult(s, s, frac, t if s > 0 else "unknown", {t: s}, {}, changed, {})

    def info(self):
        return ModelInfo("mock-change", "1.0.0", "change", None, "mock", "internal", "built-in mock")


class NeuralChangeDetector(BaseChangeDetector):
    """Plug-in point for a trained siamese network (e.g. exported ChangeFormer/BIT/ChangeStar),
    loaded from local TorchScript: (float[1,2C,H,W]) -> (prob_map float[1,1,H,W], logits_type float[1,K]).
    Same PairResult contract, so APIs and the temporal engine are unchanged."""

    def __init__(self, model_path: str, band_mapping: dict[str, int], device: str = "cpu"):
        try:
            import torch
        except ImportError as e:
            raise ModelLoadError("PyTorch required for NeuralChangeDetector") from e
        p = Path(model_path)
        if not p.exists():
            raise ModelLoadError(f"Change model not found at {p}")
        self.torch, self.device = torch, device
        self.net = torch.jit.load(str(p), map_location=device).eval()
        self.card = load_model_card(p)
        self.types = self.card.get("change_types", CHANGE_TYPES)
        self.band_mapping = band_mapping
        self._checksum = path_checksum(p)
        self._path = str(p)
        self._fallback = FeatureDifferenceChangeDetector(band_mapping)

    def compare(self, before, after):
        torch = self.torch
        common = before.clear & after.clear
        x = torch.from_numpy(np.concatenate([before.image, after.image])[None].astype(np.float32))
        with torch.inference_mode():
            prob, logits = self.net(x.to(self.device))
        prob = prob[0, 0].cpu().numpy()
        changed = common & (prob > 0.5)
        frac = float(changed.sum() / max(common.sum(), 1))
        probs = torch.softmax(logits[0], -1).cpu().numpy()
        ts = {t: round(float(p), 4) for t, p in zip(self.types, probs)}
        # reuse interpretable suppression factors (registration, season, sensor, geometry)
        ref = self._fallback.compare(before, after)
        suppression = float(np.prod(list(ref.factors.values()))) if ref.factors else 1.0
        raw = float(prob[common].mean()) if common.any() else 0.0
        return PairResult(round(raw * suppression, 4), round(raw, 4), round(frac, 4),
                          max(ts, key=ts.get), ts, ref.factors, changed, ref.diagnostics)

    def info(self):
        return ModelInfo(self.card.get("name", "neural-change"), str(self.card.get("version", "1.0.0")),
                         "change", self._path, self._checksum, self.card.get("license"),
                         self.card.get("source"))
