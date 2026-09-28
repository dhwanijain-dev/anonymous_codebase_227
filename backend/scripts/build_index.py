#!/usr/bin/env python
"""Vector index maintenance.
  reconcile (default): make the index match the DB, restoring vectors from backups
  rebuild:             rebuild the index from durable vector backups (e.g. after FAISS_INDEX_TYPE change)
  reembed:             re-encode every tile with the *currently configured* model into its own index
"""
import argparse
import json

import _bootstrap

p = argparse.ArgumentParser()
p.add_argument("mode", nargs="?", default="reconcile", choices=["reconcile", "rebuild", "reembed"])
p.add_argument("--batch", type=int, default=64)
a = p.parse_args()
_bootstrap.init()
from sqlalchemy import select  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.db.models import Tile  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.geo import raster  # noqa: E402
from app.services.embeddings.index_service import EmbeddingIndexService  # noqa: E402
from app.storage import get_storage  # noqa: E402

with SessionLocal() as db:
    svc = EmbeddingIndexService(db)
    if a.mode == "reconcile":
        out = svc.reconcile()
    elif a.mode == "rebuild":
        out = svc.rebuild()
    else:
        s, st, n, last = get_settings(), get_storage(), 0, -1
        while True:
            tiles = list(db.scalars(select(Tile).where(Tile.id > last).order_by(Tile.id).limit(a.batch)))
            if not tiles:
                break
            last = tiles[-1].id
            imgs = []
            for t in tiles:
                arr, meta = raster.read_raster(st.get_path(t.raster_path))
                valid = raster.valid_mask(arr, meta["nodata"])
                scale = raster.reflectance_scale(meta["dtype"], float(arr.max()), s.REFLECTANCE_SCALE)
                mask, _ = raster.read_raster(st.get_path(t.mask_path))
                imgs.append((raster.normalize(arr, valid, scale), valid, mask[0] == 0))
            rows = svc.add_tile_vectors([t.tile_id for t in tiles], svc.model.encode_images(imgs), f"reembed/{last:010d}")
            db.commit()
            svc.persist()
            n += len(rows)
        out = {"reembedded": n, "model": svc.info.key, "index_count": svc.store.count()}
print(json.dumps(out, indent=2))
