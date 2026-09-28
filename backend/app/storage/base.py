from abc import ABC, abstractmethod
from pathlib import Path


class StorageBackend(ABC):
    """Key-addressed blob storage. Keys are POSIX-style relative paths, e.g. 'tiles/<scene>/<tile>.tif'."""

    @abstractmethod
    def save(self, key: str, data: bytes) -> str: ...

    @abstractmethod
    def read(self, key: str) -> bytes: ...

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...

    @abstractmethod
    def get_path(self, key: str) -> Path:
        """Local filesystem path usable by GDAL/Rasterio (may be a cache copy for object stores)."""

    def commit(self, key: str) -> None:
        """Called after a file was written directly to get_path(key). No-op for local disk."""
        return None
