"""Similar-site discovery and archive clustering (memory-bounded, batched)."""
from __future__ import annotations

from datetime import datetime

import numpy as np
from shapely.geometry import MultiPoint
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import ValidationError
from app.db.models import Embedding, Tile
from app.services.registry import get_embedding_model, get_vector_store
from app.services.retrieval.service import RetrievalService, SearchParams
from app.vector.metadata_filter import TileFilter, apply_tile_filter

ALGORITHMS = ("hdbscan", "kmeans", "dbscan")


class DiscoveryService:
    def __init__(self, db: Session):
        self.db = db
        self.s = get_settings()
        self.model = get_embedding_model()
        self.minfo = self.model.info()
        self.store = get_vector_store(self.model)

    def similar_sites(self, tile_id: str, top_k: int, min_quality: float | None, bbox=None,
                      date_from=None, date_to=None) -> dict:
        p = SearchParams(top_k=top_k, min_quality=min_quality, bbox=bbox, date_from=date_from, date_to=date_to)
        return RetrievalService(self.db).similar_to_tile(tile_id, p)

    def _iter_members(self, f: TileFilter):
        """Yield (tile_id, vector_id, cx, cy) in pages — never loads the archive at once."""
        dialect = self.db.get_bind().dialect.name
        last, batch = -1, self.s.CLUSTER_BATCH_SIZE
        while True:
            stmt = (select(Tile.id, Tile.tile_id, Embedding.vector_id, Tile.min_x, Tile.min_y, Tile.max_x, Tile.max_y)
                    .join(Embedding, Embedding.tile_id == Tile.tile_id)
                    .where(Embedding.model_name == self.minfo.name, Embedding.model_version == self.minfo.version,
                           Tile.id > last).order_by(Tile.id).limit(batch))
            rows = list(self.db.execute(apply_tile_filter(stmt, f, dialect)).tuples())
            if not rows:
                return
            for r in rows:
                yield r[1], r[2], (r[3] + r[5]) / 2, (r[4] + r[6]) / 2
            last = rows[-1][0]

    def cluster(self, bbox: list[float] | None, date_from: datetime | None, date_to: datetime | None,
                algorithm: str = "hdbscan", min_cluster_size: int = 5, n_clusters: int = 8,
                min_quality: float | None = None, eps: float = 0.15) -> dict:
        if algorithm not in ALGORITHMS:
            raise ValidationError(f"algorithm must be one of {ALGORITHMS}")
        f = TileFilter(bbox=bbox, date_from=date_from, date_to=date_to, min_quality=min_quality)
        cap = self.s.CLUSTER_MAX_POINTS
        rng = np.random.default_rng(0)
        # reservoir sampling keeps memory bounded regardless of archive size
        members, seen = [], 0
        for m in self._iter_members(f):
            seen += 1
            if len(members) < cap:
                members.append(m)
            else:
                j = rng.integers(0, seen)
                if j < cap:
                    members[j] = m
        if len(members) < max(2, min_cluster_size):
            return {"algorithm": algorithm, "clusters": [], "n_points": len(members), "total_matching": seen,
                    "noise": len(members), "sampled": seen > cap}

        vids = [m[1] for m in members]
        X = np.concatenate([self.store.get_vectors(vids[i:i + self.s.CLUSTER_BATCH_SIZE])
                            for i in range(0, len(vids), self.s.CLUSTER_BATCH_SIZE)])
        if algorithm == "hdbscan":
            from sklearn.cluster import HDBSCAN

            labels = HDBSCAN(min_cluster_size=min_cluster_size, metric="euclidean").fit_predict(X)
        elif algorithm == "dbscan":
            from sklearn.cluster import DBSCAN

            labels = DBSCAN(eps=eps, min_samples=min_cluster_size, metric="cosine").fit_predict(X)
        else:
            from sklearn.cluster import MiniBatchKMeans

            k = min(n_clusters, len(X))
            km = MiniBatchKMeans(n_clusters=k, random_state=0, batch_size=self.s.CLUSTER_BATCH_SIZE, n_init=3)
            for i in range(0, len(X), self.s.CLUSTER_BATCH_SIZE):
                km.partial_fit(X[i:i + self.s.CLUSTER_BATCH_SIZE])
            labels = km.predict(X)

        clusters = []
        for lab in sorted(set(labels) - {-1}):
            idx = np.where(labels == lab)[0]
            emb = X[idx].mean(axis=0)
            emb /= max(np.linalg.norm(emb), 1e-12)
            sims = X[idx] @ emb
            reps = [members[idx[i]][0] for i in np.argsort(-sims)[: self.s.CLUSTER_REPRESENTATIVES]]
            pts = MultiPoint([(members[i][2], members[i][3]) for i in idx])
            hull = pts.convex_hull if len(idx) >= 3 else pts.envelope
            clusters.append({
                "cluster_id": int(lab), "size": int(len(idx)), "representative_tiles": reps,
                "centroid": {"type": "Point", "coordinates": [pts.centroid.x, pts.centroid.y]},
                "bounding_geometry": hull.buffer(0).__geo_interface__ if hull.area > 0 else hull.__geo_interface__,
                "representative_embedding": [round(float(v), 6) for v in emb],
                "cohesion": round(float(sims.mean()), 4),
            })
        clusters.sort(key=lambda c: -c["size"])
        return {"algorithm": algorithm, "n_points": len(members), "total_matching": seen, "sampled": seen > cap,
                "noise": int((labels == -1).sum()), "clusters": clusters,
                "embedding_model": {"name": self.minfo.name, "version": self.minfo.version}}
