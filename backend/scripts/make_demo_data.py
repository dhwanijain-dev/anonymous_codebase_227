#!/usr/bin/env python
"""Write a synthetic 6-date Sentinel-2-like time series (with a construction event and a cloudy
acquisition) into DATA_ROOT/raw/demo for smoke-testing without real imagery."""
import _bootstrap  # noqa: F401

from app.core.config import get_settings  # noqa: E402
from tests.synth import build_series, scene_bbox  # noqa: E402

out = build_series(get_settings().data_dir("raw") / "demo")
print("wrote:", *map(str, out.values()), sep="\n  ")
print("AOI bbox:", [round(v, 5) for v in scene_bbox()])
