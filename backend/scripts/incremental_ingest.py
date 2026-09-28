#!/usr/bin/env python
"""Discover and ingest only new/changed imagery (appends to the vector index, never rebuilds).
Cron example:  */30 * * * *  cd /app && python scripts/incremental_ingest.py"""
import argparse
import json

import _bootstrap

p = argparse.ArgumentParser()
p.add_argument("--dir", action="append", help="scan dir (relative to DATA_ROOT or absolute); repeatable")
p.add_argument("--dry-run", action="store_true")
a = p.parse_args()
_bootstrap.init()
from app.db.session import SessionLocal  # noqa: E402
from app.services.ingestion.pipeline import IngestionService  # noqa: E402

with SessionLocal() as db:
    svc = IngestionService(db)
    if a.dry_run:
        print("\n".join(svc.discover(a.dir)) or "nothing new")
    else:
        out = svc.ingest_incremental(a.dir)
        print(json.dumps({k: v for k, v in out.items() if k != "results"}, indent=2, default=str))
