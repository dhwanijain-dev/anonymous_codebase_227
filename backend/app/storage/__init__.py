from functools import lru_cache

from app.core.config import get_settings
from app.storage.base import StorageBackend


@lru_cache
def get_storage() -> StorageBackend:
    s = get_settings()
    if s.STORAGE_BACKEND == "minio":
        from app.storage.minio import MinioStorageBackend

        return MinioStorageBackend(s.MINIO_ENDPOINT, s.MINIO_ACCESS_KEY, s.MINIO_SECRET_KEY, s.MINIO_BUCKET, s.DATA_ROOT)
    from app.storage.local import LocalStorageBackend

    return LocalStorageBackend(s.DATA_ROOT)
