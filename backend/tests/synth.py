"""Synthetic multi-temporal GeoTIFFs with known ground truth (4 bands: B,G,R,NIR, uint16 x10000)."""
from datetime import datetime
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin

ORIGIN = (499200.0, 1400320.0)  # UTM 43N, aligned to the 2560 m tile grid (256 px x 10 m)
CRS = "EPSG:32643"


def landscape(seed: int = 0, size: int = 512) -> np.ndarray:
    rng = np.random.default_rng(seed)
    b = np.zeros((4, size, size), np.float32)
    # vegetation background
    b[0], b[1], b[2], b[3] = 0.04, 0.08, 0.05, 0.35
    b += rng.normal(0, 0.008, b.shape).astype(np.float32)
    # river along the left: rows all, cols 20..60
    b[:, :, 20:60] = np.array([0.06, 0.08, 0.04, 0.02])[:, None, None]
    return b


def add_construction(b: np.ndarray, r0=300, c0=300, h=120, w=140) -> np.ndarray:
    b = b.copy()
    blk = b[:, r0:r0 + h, c0:c0 + w]
    blk[:] = np.array([0.22, 0.24, 0.26, 0.28])[:, None, None]
    blk[:, ::12, :] = 0.12  # structure edges
    blk[:, :, ::15] = 0.12
    return b


def add_cloud(b: np.ndarray, r0=260, c0=260, h=240, w=240) -> np.ndarray:
    b = b.copy()
    b[:, r0:r0 + h, c0:c0 + w] = 0.85
    return b


def write(path: Path, b: np.ndarray, when: datetime, platform="Sentinel-2A", sensor="MSI") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = np.clip(b * 10000, 1, 10000).astype(np.uint16)
    with rasterio.open(path, "w", driver="GTiff", width=data.shape[2], height=data.shape[1], count=4,
                       dtype="uint16", crs=CRS, transform=from_origin(*ORIGIN, 10, 10), nodata=0) as dst:
        dst.write(data)
        dst.update_tags(ACQUISITION_TIME=when.isoformat(), PLATFORM=platform, SENSOR=sensor)
    return path


def build_series(raw: Path) -> dict[str, Path]:
    """t0,t1 before; t2 cloudy over the site; t3,t4,t5 after construction."""
    base = landscape(0)
    out = {
        "t0": write(raw / "S2A_20230110.tif", landscape(1), datetime(2023, 1, 10)),
        "t1": write(raw / "S2A_20230301.tif", landscape(2), datetime(2023, 3, 1)),
        "t2": write(raw / "S2A_20230501.tif", add_cloud(add_construction(landscape(3))), datetime(2023, 5, 1)),
        "t3": write(raw / "S2A_20230701.tif", add_construction(landscape(4)), datetime(2023, 7, 1)),
        "t4": write(raw / "S2A_20230901.tif", add_construction(landscape(5)), datetime(2023, 9, 1)),
        "t5": write(raw / "S2A_20231101.tif", add_construction(landscape(6)), datetime(2023, 11, 1)),
    }
    del base
    return out


# bbox (lon/lat) covering the synthetic scene
def scene_bbox() -> list[float]:
    from pyproj import Transformer

    tr = Transformer.from_crs(CRS, "EPSG:4326", always_xy=True)
    x0, y0 = ORIGIN
    lon0, lat0 = tr.transform(x0, y0 - 5120)
    lon1, lat1 = tr.transform(x0 + 5120, y0)
    return [min(lon0, lon1), min(lat0, lat1), max(lon0, lon1), max(lat0, lat1)]
