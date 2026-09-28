"""Raster I/O: validation, metadata extraction, grid-aligned tiling, normalisation, thumbnails.

All GDAL/Rasterio usage is confined to this package so the ML and business layers
only ever see numpy arrays + plain metadata.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.enums import Resampling
from rasterio.transform import from_origin
from rasterio.warp import reproject
from rasterio.windows import from_bounds
from shapely.geometry import Polygon, box, mapping
from shapely.ops import transform as shp_transform

from app.core.exceptions import IngestionError

SUPPORTED_EXT = {".tif", ".tiff", ".gtiff", ".cog"}
CHUNK = 8 * 1024 * 1024


# --------------------------------------------------------------------------- checksum
def file_checksum(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


# --------------------------------------------------------------------------- metadata
_FILENAME_PLATFORMS = [
    (re.compile(r"^S2([ABC])_", re.I), lambda m: (f"Sentinel-2{m.group(1).upper()}", "MSI")),
    (re.compile(r"^S1([ABC])_", re.I), lambda m: (f"Sentinel-1{m.group(1).upper()}", "C-SAR")),
    (re.compile(r"^L[COTEM]0?([789])", re.I), lambda m: (f"Landsat-{m.group(1)}", "OLI" if m.group(1) in "89" else "ETM+/TM")),
    (re.compile(r"^PS", re.I), lambda m: ("PlanetScope", "PS")),
]
_DATE_PATTERNS = [
    (re.compile(r"(\d{8}T\d{6})"), "%Y%m%dT%H%M%S"),
    (re.compile(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})"), "%Y-%m-%dT%H:%M:%S"),
    (re.compile(r"(\d{4}:\d{2}:\d{2} \d{2}:\d{2}:\d{2})"), "%Y:%m:%d %H:%M:%S"),
    (re.compile(r"(\d{4}-\d{2}-\d{2})"), "%Y-%m-%d"),
    (re.compile(r"(?<!\d)((?:19|20)\d{6})(?!\d)"), "%Y%m%d"),
]
_TIME_TAGS = ("ACQUISITION_TIME", "ACQUISITION_DATE", "DATE_ACQUIRED", "SENSING_TIME", "DATETIME",
              "datetime", "TIFFTAG_DATETIME", "acquisition_time")
_SENSOR_TAGS = ("SENSOR", "SENSOR_ID", "INSTRUMENT", "instruments", "sensor")
_PLATFORM_TAGS = ("PLATFORM", "SPACECRAFT_ID", "SATELLITE", "MISSION", "platform")


def parse_datetime(value: str) -> datetime | None:
    value = str(value).strip()
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    for rx, fmt in _DATE_PATTERNS:
        m = rx.search(value)
        if m:
            try:
                return datetime.strptime(m.group(1), fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return None


@dataclass
class RasterMetadata:
    path: Path
    filename: str
    crs: str
    epsg: int | None
    transform: tuple
    resolution: float
    res_x: float
    res_y: float
    width: int
    height: int
    bands: int
    dtype: str
    nodata: float | None
    bounds_native: tuple[float, float, float, float]
    footprint_wgs84: Polygon
    acquisition_time: datetime | None
    sensor: str | None
    platform: str | None
    processing_level: str | None
    cloud_percentage: float | None
    is_cog: bool
    north_up: bool
    extra: dict[str, Any] = field(default_factory=dict)


def _sidecar(path: Path) -> dict[str, Any]:
    """Optional STAC-like JSON next to the raster: foo.tif -> foo.json."""
    for cand in (path.with_suffix(".json"), path.with_name(path.name + ".json")):
        if cand.exists():
            try:
                doc = json.loads(cand.read_text())
                return doc.get("properties", doc)
            except (json.JSONDecodeError, OSError):
                return {}
    return {}


def to_wgs84_polygon(bounds: tuple, crs, densify: int = 16) -> Polygon:
    poly = box(*bounds)
    if crs is None:
        return poly
    if str(crs).upper() in ("EPSG:4326", "OGC:CRS84"):
        return poly
    poly = poly.segmentize(max(poly.length / (4 * densify), 1e-9))
    tr = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    return shp_transform(tr.transform, poly)


def validate_raster(path: Path) -> None:
    if not path.exists() or not path.is_file():
        raise IngestionError(f"File not found: {path}")
    if path.suffix.lower() not in SUPPORTED_EXT:
        raise IngestionError(f"Unsupported extension {path.suffix}; expected GeoTIFF/COG")
    try:
        with rasterio.open(path) as ds:
            if ds.driver != "GTiff":
                raise IngestionError(f"Unsupported driver {ds.driver}")
            if ds.crs is None:
                raise IngestionError("Raster has no CRS; georeferencing is required")
            if ds.transform.is_identity:
                raise IngestionError("Raster has identity geotransform; georeferencing is required")
            if ds.width == 0 or ds.height == 0 or ds.count == 0:
                raise IngestionError("Empty raster")
    except rasterio.errors.RasterioIOError as e:
        raise IngestionError(f"Unreadable raster: {e}") from e


def extract_metadata(path: Path, overrides: dict[str, Any] | None = None) -> RasterMetadata:
    overrides = {k: v for k, v in (overrides or {}).items() if v is not None}
    side = _sidecar(path)
    with rasterio.open(path) as ds:
        tags = {**ds.tags(), **{k: v for k, v in ds.tags(ns="IMAGE_STRUCTURE").items()}}
        t = ds.transform
        res_x, res_y = abs(t.a), abs(t.e)
        north_up = t.b == 0 and t.d == 0 and t.e < 0
        layout = tags.get("LAYOUT", "")
        is_cog = layout.upper() == "COG" or (ds.profile.get("tiled", False) and len(ds.overviews(1)) > 0)
        footprint = to_wgs84_polygon(tuple(ds.bounds), ds.crs)

        def first(keys, *sources):
            for src in sources:
                for k in keys:
                    if k in src and src[k] not in (None, ""):
                        return src[k]
            return None

        acq = overrides.get("acquisition_time")
        if isinstance(acq, str):
            acq = parse_datetime(acq)
        if acq is None:
            raw = first(_TIME_TAGS, side, tags)
            acq = parse_datetime(raw) if raw else parse_datetime(path.stem)
        sensor = overrides.get("sensor") or first(_SENSOR_TAGS, side, tags)
        platform = overrides.get("platform") or first(_PLATFORM_TAGS, side, tags)
        if isinstance(sensor, list):
            sensor = ",".join(sensor)
        if not (sensor and platform):
            for rx, fn in _FILENAME_PLATFORMS:
                m = rx.search(path.name)
                if m:
                    p, s = fn(m)
                    platform, sensor = platform or p, sensor or s
                    break
        level = overrides.get("processing_level") or first(
            ("PROCESSING_LEVEL", "processing:level", "processing_level"), side, tags
        )
        if not level:
            m = re.search(r"(L1C|L2A|L1TP|L2SP|L1GT|L2)", path.name)
            level = m.group(1) if m else None
        cloud = first(("eo:cloud_cover", "CLOUD_COVER", "cloud_cover"), side, tags)
        extra = {
            "view_off_nadir": first(("view:off_nadir", "VIEW_ANGLE", "OFF_NADIR"), side, tags),
            "sun_elevation": first(("view:sun_elevation", "SUN_ELEVATION"), side, tags),
            "sun_azimuth": first(("view:sun_azimuth", "SUN_AZIMUTH"), side, tags),
            "band_descriptions": list(ds.descriptions),
            "tags": {k: str(v)[:256] for k, v in tags.items()},
        }
        return RasterMetadata(
            path=path, filename=path.name, crs=ds.crs.to_string(), epsg=ds.crs.to_epsg(),
            transform=tuple(t)[:6], resolution=float((res_x + res_y) / 2), res_x=res_x, res_y=res_y,
            width=ds.width, height=ds.height, bands=ds.count, dtype=ds.dtypes[0], nodata=ds.nodata,
            bounds_native=tuple(ds.bounds), footprint_wgs84=footprint,
            acquisition_time=acq, sensor=str(sensor) if sensor else None,
            platform=str(platform) if platform else None, processing_level=level,
            cloud_percentage=float(cloud) if cloud is not None else None, is_cog=bool(is_cog),
            north_up=north_up, extra=extra,
        )


# --------------------------------------------------------------------------- normalisation
def reflectance_scale(dtype: str, sample_max: float, configured: float | None) -> float:
    if configured:
        return configured
    if dtype == "uint8":
        return 255.0
    if dtype in ("uint16", "int16", "uint32", "int32"):
        return 10000.0 if sample_max > 255 else 255.0
    return 1.0 if sample_max <= 1.5 else float(sample_max)


def normalize(arr: np.ndarray, valid: np.ndarray, scale: float) -> np.ndarray:
    out = arr.astype(np.float32) / np.float32(scale)
    out = np.clip(out, 0.0, 1.0)
    out[:, ~valid] = 0.0
    return out


def valid_mask(arr: np.ndarray, nodata: float | None) -> np.ndarray:
    if nodata is not None and not (isinstance(nodata, float) and math.isnan(nodata)):
        invalid = np.all(arr == nodata, axis=0)
    else:
        invalid = np.all(arr == 0, axis=0)
    if np.issubdtype(arr.dtype, np.floating):
        invalid |= np.any(~np.isfinite(arr), axis=0)
    return ~invalid


# --------------------------------------------------------------------------- tiling
@dataclass
class TileWindow:
    gx: int
    gy: int
    bounds: tuple[float, float, float, float]  # native CRS
    transform: Any
    location_key: str


def grid_windows(meta: RasterMetadata, tile_size: int) -> Iterator[TileWindow]:
    """Tiles aligned to a global grid anchored at CRS origin, so scenes sharing a CRS and
    resolution produce identical tile footprints -> stable location keys for time series."""
    if not meta.north_up:
        raise IngestionError("Rotated/skewed rasters are not supported; warp to north-up first")
    res = meta.res_x
    g = tile_size * res
    left, bottom, right, top = meta.bounds_native
    gx0, gx1 = math.floor(left / g), math.ceil(right / g) - 1
    gy0, gy1 = math.floor(bottom / g), math.ceil(top / g) - 1
    crs_key = meta.epsg or hashlib.sha1(meta.crs.encode()).hexdigest()[:8]
    for gy in range(gy1, gy0 - 1, -1):
        for gx in range(gx0, gx1 + 1):
            b = (gx * g, gy * g, (gx + 1) * g, (gy + 1) * g)
            yield TileWindow(
                gx=gx, gy=gy, bounds=b,
                transform=from_origin(b[0], b[3], res, meta.res_y),
                location_key=f"{crs_key}:{res:g}:{tile_size}:{gx}:{gy}",
            )


def read_window(ds, tw: TileWindow, tile_size: int, nodata) -> np.ndarray:
    win = from_bounds(*tw.bounds, transform=ds.transform)
    fill = nodata if nodata is not None else 0
    return ds.read(
        window=win, out_shape=(ds.count, tile_size, tile_size), boundless=True,
        fill_value=fill, resampling=Resampling.nearest,
    )


def write_tile(path: Path, arr: np.ndarray, transform, crs, nodata, fmt: str = "COG") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    profile = dict(
        count=arr.shape[0], height=arr.shape[1], width=arr.shape[2], dtype=arr.dtype.name,
        crs=crs, transform=transform, nodata=nodata, compress="deflate",
    )
    tmp = path.with_suffix(".tmp.tif")
    if fmt.upper() == "COG":
        try:
            with rasterio.open(tmp, "w", driver="COG", **profile) as dst:
                dst.write(arr)
            tmp.replace(path)
            return
        except Exception:  # older GDAL without COG driver -> tiled GTiff
            tmp.unlink(missing_ok=True)
    with rasterio.open(tmp, "w", driver="GTiff", tiled=True, blockxsize=min(256, arr.shape[2]),
                       blockysize=min(256, arr.shape[1]), **profile) as dst:
        dst.write(arr)
    tmp.replace(path)


def write_mask(path: Path, mask: np.ndarray, transform, crs) -> None:
    write_tile(path, mask[None].astype(np.uint8), transform, crs, None, fmt="GTiff")


def read_raster(path: Path) -> tuple[np.ndarray, dict]:
    with rasterio.open(path) as ds:
        return ds.read(), {"transform": ds.transform, "crs": ds.crs, "nodata": ds.nodata,
                           "dtype": ds.dtypes[0], "bounds": tuple(ds.bounds)}


def align_to(src: np.ndarray, src_meta: dict, dst_meta: dict, shape: tuple[int, int]) -> np.ndarray:
    """Reproject `src` onto the grid of `dst_meta` (used when observations are not grid-identical)."""
    if src_meta["crs"] == dst_meta["crs"] and src_meta["transform"] == dst_meta["transform"] \
            and src.shape[1:] == shape:
        return src
    out = np.zeros((src.shape[0], *shape), dtype=src.dtype)
    for b in range(src.shape[0]):
        reproject(src[b], out[b], src_transform=src_meta["transform"], src_crs=src_meta["crs"],
                  dst_transform=dst_meta["transform"], dst_crs=dst_meta["crs"],
                  resampling=Resampling.bilinear, src_nodata=src_meta.get("nodata"), dst_nodata=0)
    return out


# --------------------------------------------------------------------------- thumbnails
def make_thumbnail(norm: np.ndarray, bands: dict[str, np.ndarray], size: int, path: Path) -> None:
    from PIL import Image

    if all(k in bands for k in ("red", "green", "blue")):
        rgb = np.stack([bands["red"], bands["green"], bands["blue"]], axis=-1)
    else:
        rgb = np.repeat(norm[0][..., None], 3, axis=-1)
    valid = rgb.max(axis=-1) > 0
    if valid.any():
        lo, hi = np.percentile(rgb[valid], [2, 98])
        rgb = np.clip((rgb - lo) / max(hi - lo, 1e-6), 0, 1)
    img = Image.fromarray((rgb * 255).astype(np.uint8)).resize((size, size), Image.BILINEAR)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, format="PNG")


def geojson(geom_wkt: str | None) -> dict | None:
    if not geom_wkt:
        return None
    from shapely import wkt

    return mapping(wkt.loads(geom_wkt))
