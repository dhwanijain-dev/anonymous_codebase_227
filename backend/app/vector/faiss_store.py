"""Persistent FAISS store (cosine via inner product on L2-normalised vectors).

Layout under <index_dir>/<namespace>/:
    index.faiss      IndexIDMap2(IndexFlatIP | IndexHNSWFlat)
    keys.json        {vector_id: tile_id}
    tombstones.json  ids logically deleted (physically removed on rebuild)
Writes are atomic (tmp + rename) and guarded by an RLock.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import faiss
import numpy as np

from app.vector.base import VectorHit, VectorStore


def _norm(v: np.ndarray) -> np.ndarray:
    v = np.ascontiguousarray(np.atleast_2d(v), dtype=np.float32)
    faiss.normalize_L2(v)
    return v


class FAISSVectorStore(VectorStore):
    def __init__(self, directory: Path, dim: int, index_type: str = "flat", hnsw_m: int = 32):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.dim, self.index_type, self.hnsw_m = dim, index_type, hnsw_m
        self._lock = threading.RLock()
        self.keys: dict[int, str] = {}
        self.rev: dict[str, list[int]] = {}
        self.tombstones: set[int] = set()
        self.index = self._new_index()
        self.load()

    # ------------------------------------------------------------------ internals
    def _new_index(self):
        if self.index_type == "hnsw":
            base = faiss.IndexHNSWFlat(self.dim, self.hnsw_m, faiss.METRIC_INNER_PRODUCT)
            base.hnsw.efSearch = 128
        else:
            base = faiss.IndexFlatIP(self.dim)
        return faiss.IndexIDMap2(base)

    def _next_id(self) -> int:
        return (max(self.keys) + 1) if self.keys else 0

    def _index_rev(self):
        self.rev = {}
        for i, k in self.keys.items():
            self.rev.setdefault(k, []).append(i)

    def _write(self, name: str, data: bytes):
        tmp = self.dir / f".{name}.tmp"
        tmp.write_bytes(data)
        os.replace(tmp, self.dir / name)

    # ------------------------------------------------------------------ API
    def add(self, vectors, keys):
        with self._lock:
            start = self._next_id()
            ids = list(range(start, start + len(keys)))
            self.add_with_ids(vectors, ids, keys)
            return ids

    def add_with_ids(self, vectors, ids, keys):
        if len(ids) == 0:
            return
        v = _norm(vectors)
        if v.shape[1] != self.dim:
            raise ValueError(f"Vector dim {v.shape[1]} != index dim {self.dim}")
        with self._lock:
            self.index.add_with_ids(v, np.asarray(ids, dtype=np.int64))
            for i, k in zip(ids, keys):
                self.keys[int(i)] = k
                self.rev.setdefault(k, []).append(int(i))
                self.tombstones.discard(int(i))

    def search(self, query, k):
        with self._lock:
            n = self.index.ntotal
            if n == 0 or k <= 0:
                return []
            kk = min(n, k + len(self.tombstones))
            D, I = self.index.search(_norm(query), kk)
            hits = []
            for d, i in zip(D[0], I[0]):
                if i < 0 or int(i) in self.tombstones:
                    continue
                hits.append(VectorHit(int(i), self.keys.get(int(i), ""), float(d)))
                if len(hits) >= k:
                    break
            return hits

    def get_vectors(self, vector_ids):
        with self._lock:
            if not vector_ids:
                return np.zeros((0, self.dim), np.float32)
            return np.stack([self.index.reconstruct(int(i)) for i in vector_ids])

    def score_subset(self, query, vector_ids):
        ids = [i for i in vector_ids if i in self.keys and i not in self.tombstones]
        if not ids:
            return []
        q = _norm(query)[0]
        out = []
        for s in range(0, len(ids), 4096):  # chunked to bound memory
            chunk = ids[s:s + 4096]
            sims = self.get_vectors(chunk) @ q
            out += [VectorHit(i, self.keys[i], float(x)) for i, x in zip(chunk, sims)]
        return sorted(out, key=lambda h: -h.score)

    def ids_for_keys(self, keys):
        with self._lock:
            return [i for k in keys for i in self.rev.get(k, []) if i not in self.tombstones]

    def contains(self, vector_id):
        return vector_id in self.keys and vector_id not in self.tombstones

    def delete(self, vector_ids):
        with self._lock:
            n = 0
            for i in vector_ids:
                if i in self.keys and i not in self.tombstones:
                    self.tombstones.add(int(i))
                    n += 1
            # flat indexes support physical removal cheaply
            if self.index_type == "flat" and vector_ids:
                self.index.remove_ids(np.asarray(list(vector_ids), dtype=np.int64))
                for i in vector_ids:
                    k = self.keys.pop(int(i), None)
                    if k and k in self.rev:
                        self.rev[k] = [x for x in self.rev[k] if x != i]
                    self.tombstones.discard(int(i))
            return n

    def count(self):
        with self._lock:
            return self.index.ntotal - len(self.tombstones)

    def save(self):
        with self._lock:
            self._write("index.faiss", faiss.serialize_index(self.index).tobytes())
            self._write("keys.json", json.dumps(self.keys).encode())
            self._write("tombstones.json", json.dumps(sorted(self.tombstones)).encode())

    def load(self):
        with self._lock:
            p = self.dir / "index.faiss"
            if p.exists():
                self.index = faiss.deserialize_index(np.frombuffer(p.read_bytes(), dtype=np.uint8))
                self.keys = {int(k): v for k, v in json.loads((self.dir / "keys.json").read_text()).items()}
                tp = self.dir / "tombstones.json"
                self.tombstones = set(json.loads(tp.read_text())) if tp.exists() else set()
                self._index_rev()

    def rebuild(self, vectors=None, ids=None, keys=None):
        with self._lock:
            if vectors is None:
                live = [i for i in self.keys if i not in self.tombstones]
                vectors, ids, keys = self.get_vectors(live), live, [self.keys[i] for i in live]
            self.index = self._new_index()
            self.keys, self.rev, self.tombstones = {}, {}, set()
            self.add_with_ids(vectors, list(ids), list(keys))
            self.save()
