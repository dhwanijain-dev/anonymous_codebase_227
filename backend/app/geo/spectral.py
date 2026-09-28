"""Spectral helpers shared by the quality engine, mock embedding and change detector."""
from __future__ import annotations

import numpy as np

EPS = 1e-6

# Order of the hand-crafted descriptor used by the mock embedding / text prototypes.
FEATURE_NAMES = [
    "brightness", "contrast", "edge_density", "ndvi", "ndwi", "veg_frac", "water_frac",
    "bright_frac", "dark_frac", "texture", "linearity", "red", "green", "blue", "nir", "built_frac",
]
N_FEATURES = len(FEATURE_NAMES)
# Rough archive-typical centre; subtracting it makes cosine similarity meaningful.
FEATURE_CENTER = np.array(
    [0.18, 0.08, 0.12, 0.25, -0.2, 0.35, 0.05, 0.05, 0.08, 0.5, 0.2, 0.12, 0.12, 0.1, 0.3, 0.1],
    dtype=np.float32,
)
FEATURE_SCALE = np.array(
    [0.12, 0.06, 0.1, 0.3, 0.3, 0.35, 0.15, 0.12, 0.15, 0.25, 0.2, 0.1, 0.1, 0.1, 0.15, 0.15],
    dtype=np.float32,
)


def band_roles(norm: np.ndarray, mapping: dict[str, int]) -> dict[str, np.ndarray]:
    """Map spectral roles to arrays; approximate missing roles so every tile gets all four."""
    n = norm.shape[0]
    out: dict[str, np.ndarray] = {}
    for role, idx in mapping.items():
        if 1 <= idx <= n:
            out[role] = norm[idx - 1]
    if n == 1:
        for r in ("blue", "green", "red", "nir"):
            out.setdefault(r, norm[0])
    if n == 3 and "nir" not in out:
        # RGB-only sensors: green serves as a weak NIR proxy (VARI-like vegetation cue)
        out["nir"] = out.get("green", norm[1])
    for r in ("blue", "green", "red"):
        out.setdefault(r, norm[min(n - 1, {"blue": 0, "green": 1, "red": 2}[r])])
    out.setdefault("nir", norm[min(n - 1, 3)])
    return out


def indices(b: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    ndvi = (b["nir"] - b["red"]) / (b["nir"] + b["red"] + EPS)
    ndwi = (b["green"] - b["nir"]) / (b["green"] + b["nir"] + EPS)
    bright = (b["red"] + b["green"] + b["blue"]) / 3.0
    return {"ndvi": ndvi, "ndwi": ndwi, "brightness": bright}


def gradient_magnitude(x: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    gy, gx = np.gradient(x.astype(np.float32))
    return np.hypot(gx, gy), gx, gy


def linearity(gx: np.ndarray, gy: np.ndarray, mag: np.ndarray, valid: np.ndarray) -> float:
    """Orientation coherence of strong gradients (structure tensor); roads/runways score high."""
    strong = valid & (mag > np.percentile(mag[valid], 80) if valid.any() else valid)
    if strong.sum() < 16:
        return 0.0
    jxx, jyy, jxy = (gx[strong] ** 2).sum(), (gy[strong] ** 2).sum(), (gx[strong] * gy[strong]).sum()
    return float(np.sqrt((jxx - jyy) ** 2 + 4 * jxy ** 2) / (jxx + jyy + EPS))


def entropy(x: np.ndarray, bins: int = 32) -> float:
    if x.size == 0:
        return 0.0
    h, _ = np.histogram(x, bins=bins, range=(0, 1))
    p = h / max(h.sum(), 1)
    p = p[p > 0]
    return float(-(p * np.log2(p)).sum() / np.log2(bins))


def descriptor(norm: np.ndarray, valid: np.ndarray, mapping: dict[str, int],
               clear: np.ndarray | None = None) -> np.ndarray:
    """16-d physically-meaningful descriptor of a tile, computed on clear valid pixels."""
    m = valid if clear is None else (valid & clear)
    if m.sum() < 16:
        m = valid
    if m.sum() == 0:
        return FEATURE_CENTER.copy()
    b = band_roles(norm, mapping)
    ix = indices(b)
    mag, gx, gy = gradient_magnitude(ix["brightness"])
    bright = ix["brightness"][m]
    ndvi, ndwi = ix["ndvi"][m], ix["ndwi"][m]
    edge = float((mag[m] > 0.04).mean())
    built = float(((ndvi < 0.15) & (ndwi < 0.0) & (bright > 0.15)).mean())
    return np.array([
        bright.mean(), bright.std(), edge, ndvi.mean(), ndwi.mean(),
        (ndvi > 0.3).mean(), (ndwi > 0.1).mean(), (bright > 0.4).mean(), (bright < 0.06).mean(),
        entropy(bright), linearity(gx, gy, mag, m),
        b["red"][m].mean(), b["green"][m].mean(), b["blue"][m].mean(), b["nir"][m].mean(), built,
    ], dtype=np.float32)


def standardize(desc: np.ndarray) -> np.ndarray:
    return (desc - FEATURE_CENTER) / FEATURE_SCALE


def summary(desc: np.ndarray) -> dict[str, float]:
    return {k: round(float(v), 4) for k, v in zip(FEATURE_NAMES, desc)}
