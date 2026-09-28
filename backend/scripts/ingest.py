#!/usr/bin/env python
"""Ingest GeoTIFF/COG files or directories.  python scripts/ingest.py /data/raw/a.tif /data/raw/batch1/"""
import argparse
import json
from pathlib import Path

import _bootstrap

p = argparse.ArgumentParser()
p.add_argument("paths", nargs="+")
p.add_argument("--sensor"), p.add_argument("--platform"), p.add_argument("--acquisition-time")
p.add_argument("--force", action="store_true")
a = p.parse_args()
_bootstrap.init()
from app.db.session import SessionLocal  # noqa: E402
from app.geo.raster import SUPPORTED_EXT  # noqa: E402
from app.services.ingestion.pipeline import IngestionService  # noqa: E402

files = []
for x in a.paths:
    x = Path(x)
    files += sorted(str(f) for f in x.rglob("*") if f.suffix.lower() in SUPPORTED_EXT) if x.is_dir() else [str(x)]
meta = {k: v for k, v in {"sensor": a.sensor, "platform": a.platform, "acquisition_time": a.acquisition_time}.items() if v}
with SessionLocal() as db:
    out = IngestionService(db, lambda f, m: print(f"  {f:5.0%} {m}", flush=True)).ingest_batch(files, meta or None, a.force)
print(json.dumps({k: v for k, v in out.items() if k != "results"}, indent=2, default=str))
