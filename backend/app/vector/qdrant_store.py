"""Qdrant implementation of the same contract (embedded/local mode, fully offline).
Optional dependency: `pip install qdrant-client`. Select with VECTOR_BACKEND=qdrant."""
from __future__ import annotations

from pathlib import Path

import numpy as np

from app.vector.base import VectorHit, VectorStore


class QdrantVectorStore(VectorStore):
    def __init__(self, path: Path, collection: str, dim: int, url: str | None = None):
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, VectorParams

        self.client = QdrantClient(url=url) if url else QdrantClient(path=str(path))
        self.collection, self.dim = collection, dim
        self._ensure()

    def _ensure(self):
        from qdrant_client.models import Distance, VectorParams

        collection, dim = self.collection, self.dim
        if not self.client.collection_exists(collection):
            self.client.create_collection(collection, vectors_config=VectorParams(size=dim, distance=Distance.COSINE))

    def _next_id(self) -> int:
        pts, _ = self.client.scroll(self.collection, limit=10**9, with_payload=False)
        return max(int(p.id) for p in pts) + 1 if pts else 0

    def add(self, vectors, keys):
        start = self._next_id()
        ids = list(range(start, start + len(keys)))
        self.add_with_ids(vectors, ids, keys)
        return ids

    def add_with_ids(self, vectors, ids, keys):
        from qdrant_client.models import PointStruct

        self.client.upsert(self.collection, [PointStruct(id=int(i), vector=np.asarray(v).tolist(), payload={"key": k})
                                             for i, v, k in zip(ids, vectors, keys)])

    def search(self, query, k):
        res = self.client.query_points(self.collection, query=np.asarray(query).ravel().tolist(), limit=k).points
        return [VectorHit(int(p.id), p.payload["key"], float(p.score)) for p in res]

    def score_subset(self, query, vector_ids):
        from qdrant_client.models import HasIdCondition, Filter

        res = self.client.query_points(self.collection, query=np.asarray(query).ravel().tolist(),
                                       query_filter=Filter(must=[HasIdCondition(has_id=list(vector_ids))]),
                                       limit=len(vector_ids)).points
        return [VectorHit(int(p.id), p.payload["key"], float(p.score)) for p in res]

    def get_vectors(self, vector_ids):
        pts = self.client.retrieve(self.collection, ids=list(vector_ids), with_vectors=True)
        by = {p.id: p.vector for p in pts}
        return np.array([by[i] for i in vector_ids], dtype=np.float32)

    def ids_for_keys(self, keys):
        from qdrant_client.models import FieldCondition, Filter, MatchAny

        pts, _ = self.client.scroll(self.collection, scroll_filter=Filter(
            must=[FieldCondition(key="key", match=MatchAny(any=list(keys)))]), limit=10**6)
        return [int(p.id) for p in pts]

    def contains(self, vector_id):
        return bool(self.client.retrieve(self.collection, ids=[vector_id]))

    def delete(self, vector_ids):
        from qdrant_client.models import PointIdsList

        self.client.delete(self.collection, PointIdsList(points=list(vector_ids)))
        return len(vector_ids)

    def save(self):  # qdrant persists on write
        return None

    def load(self):
        return None

    def count(self):
        return self.client.count(self.collection).count

    def rebuild(self, vectors=None, ids=None, keys=None):
        if vectors is None:
            return None
        self.client.delete_collection(self.collection)
        self._ensure()
        self.add_with_ids(vectors, ids, keys)
