"""Embedding index management: idempotent incremental adds, durable vector backups,
and DB<->index reconciliation after crashes."""
from __future__ import annotations

from pathlib import Path

import numpy as np
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db.models import Embedding
from app.models.embedding_model import BaseEmbeddingModel
from app.repositories.embedding_repository import EmbeddingRepository
from app.services.registry import get_embedding_model, get_vector_store, vector_namespace
from app.storage import get_storage
from app.vector.base import VectorStore

log = get_logger(__name__)


class EmbeddingIndexService:
    def __init__(self, db: Session, model: BaseEmbeddingModel | None = None, store: VectorStore | None = None):
        self.db = db
        self.model = model or get_embedding_model()
        self.info = self.model.info()
        self.store = store or get_vector_store(self.model)
        self.repo = EmbeddingRepository(db)
        self.ns = vector_namespace(self.info)

    def add_tile_vectors(self, tile_ids: list[str], vectors: np.ndarray, batch_key: str) -> list[Embedding]:
        """Add vectors for tiles that don't have one yet for this model. Safe to call repeatedly."""
        have = self.repo.tiles_with_embeddings(tile_ids, self.info.name, self.info.version)
        keep = [i for i, t in enumerate(tile_ids) if t not in have]
        if not keep:
            return []
        tids = [tile_ids[i] for i in keep]
        vecs = np.asarray(vectors, dtype=np.float32)[keep]
        # remove orphans left by an interrupted earlier attempt (in index, not in DB)
        orphans = self.store.ids_for_keys(tids)
        if orphans:
            self.store.delete(orphans)
        # durable backup used for rebuild / reconciliation
        storage = get_storage()
        key = f"embeddings/{self.ns}/{batch_key}.npz"
        path = storage.get_path(key)
        np.savez_compressed(path, tile_ids=np.array(tids), vectors=vecs)
        storage.commit(key)

        ids = self.store.add(vecs, tids)
        rows = [Embedding(tile_id=t, embedding_type="image", model_name=self.info.name,
                          model_version=self.info.version, dimension=vecs.shape[1], vector_id=i, vector_path=key)
                for t, i in zip(tids, ids)]
        try:
            self.db.add_all(rows)
            self.db.flush()
        except Exception:
            self.store.delete(ids)
            raise
        return rows

    def persist(self) -> None:
        self.store.save()

    # ------------------------------------------------------------------ maintenance
    def _load_backup(self, key: str) -> dict[str, np.ndarray]:
        path: Path = get_storage().get_path(key)
        if not path.exists():
            return {}
        d = np.load(path)
        return {str(t): v for t, v in zip(d["tile_ids"], d["vectors"])}

    def reconcile(self) -> dict:
        """Make the index match the DB (DB is authoritative)."""
        restored, missing_backup, db_ids = 0, 0, set()
        cache: dict[str, dict[str, np.ndarray]] = {}
        for rows in self.repo.iter_all(self.info.name, self.info.version):
            need = [r for r in rows if not self.store.contains(r.vector_id)]
            db_ids |= {r.vector_id for r in rows}
            vecs, ids, keys = [], [], []
            for r in need:
                if r.vector_path not in cache:
                    cache[r.vector_path] = self._load_backup(r.vector_path) if r.vector_path else {}
                v = cache[r.vector_path].get(r.tile_id)
                if v is None:
                    missing_backup += 1
                    continue
                vecs.append(v), ids.append(r.vector_id), keys.append(r.tile_id)
            if ids:
                self.store.add_with_ids(np.stack(vecs), ids, keys)
                restored += len(ids)
        orphans = []
        if hasattr(self.store, "keys"):
            orphans = [i for i in list(self.store.keys) if i not in db_ids and self.store.contains(i)]
            if orphans:
                self.store.delete(orphans)
        if restored or orphans:
            self.store.save()
        report = {"restored": restored, "orphans_removed": len(orphans), "missing_backup": missing_backup,
                  "index_count": self.store.count(), "db_count": len(db_ids)}
        log.info(f"vector index reconcile: {report}")
        return report

    def rebuild(self) -> dict:
        """Full rebuild from durable backups (e.g. after changing FAISS_INDEX_TYPE)."""
        vecs, ids, keys = [], [], []
        cache: dict[str, dict[str, np.ndarray]] = {}
        for rows in self.repo.iter_all(self.info.name, self.info.version):
            for r in rows:
                if r.vector_path not in cache:
                    cache[r.vector_path] = self._load_backup(r.vector_path) if r.vector_path else {}
                v = cache[r.vector_path].get(r.tile_id)
                if v is None and self.store.contains(r.vector_id):
                    v = self.store.get_vectors([r.vector_id])[0]
                if v is not None:
                    vecs.append(v), ids.append(r.vector_id), keys.append(r.tile_id)
        dim = self.model.embedding_dimension()
        self.store.rebuild(np.stack(vecs) if vecs else np.zeros((0, dim), np.float32), ids, keys)
        return {"rebuilt": len(ids), "index_count": self.store.count()}
