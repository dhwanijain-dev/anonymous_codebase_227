"""Vector store contract. Stores only vectors + an integer id -> tile_id map; all
geographic/temporal/sensor filtering happens in PostgreSQL/PostGIS."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np


@dataclass
class VectorHit:
    vector_id: int
    key: str  # tile_id
    score: float  # cosine similarity in [-1, 1]


class VectorStore(ABC):
    @abstractmethod
    def add(self, vectors: np.ndarray, keys: list[str]) -> list[int]:
        """Append vectors; returns assigned vector ids (incremental, no rebuild)."""

    @abstractmethod
    def search(self, query: np.ndarray, k: int) -> list[VectorHit]: ...

    @abstractmethod
    def score_subset(self, query: np.ndarray, vector_ids: list[int]) -> list[VectorHit]:
        """Exact cosine against a pre-filtered id subset (filter-first strategy)."""

    @abstractmethod
    def get_vectors(self, vector_ids: list[int]) -> np.ndarray: ...

    @abstractmethod
    def ids_for_keys(self, keys: list[str]) -> list[int]: ...

    @abstractmethod
    def delete(self, vector_ids: list[int]) -> int: ...

    @abstractmethod
    def save(self) -> None: ...

    @abstractmethod
    def load(self) -> None: ...

    @abstractmethod
    def count(self) -> int: ...

    @abstractmethod
    def rebuild(self, vectors: np.ndarray | None = None, ids: list[int] | None = None,
                keys: list[str] | None = None) -> None:
        """Compact (drop tombstones) or rebuild from supplied vectors, preserving ids."""

    @abstractmethod
    def contains(self, vector_id: int) -> bool: ...

    def add_with_ids(self, vectors: np.ndarray, ids: list[int], keys: list[str]) -> None:
        raise NotImplementedError
