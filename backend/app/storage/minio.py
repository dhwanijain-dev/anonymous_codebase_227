"""MinIO / S3-compatible *local* object storage. Optional: requires `pip install minio`.

Files are cached under DATA_ROOT/.cache so GDAL/Rasterio can open them by path.
"""
import io
from pathlib import Path

from app.storage.base import StorageBackend


class MinioStorageBackend(StorageBackend):
    def __init__(self, endpoint: str, access_key: str, secret_key: str, bucket: str, cache_root: Path):
        from minio import Minio  # imported lazily

        self.client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=False)
        self.bucket = bucket
        self.cache = Path(cache_root) / ".cache"
        if not self.client.bucket_exists(bucket):
            self.client.make_bucket(bucket)

    def save(self, key: str, data: bytes) -> str:
        self.client.put_object(self.bucket, key, io.BytesIO(data), len(data))
        return key

    def read(self, key: str) -> bytes:
        resp = self.client.get_object(self.bucket, key)
        try:
            return resp.read()
        finally:
            resp.close()

    def exists(self, key: str) -> bool:
        try:
            self.client.stat_object(self.bucket, key)
            return True
        except Exception:
            return False

    def delete(self, key: str) -> None:
        self.client.remove_object(self.bucket, key)

    def get_path(self, key: str) -> Path:
        p = self.cache / key
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists() and self.exists(key):
            p.write_bytes(self.read(key))
        return p

    def commit(self, key: str) -> None:
        p = self.cache / key
        self.client.fput_object(self.bucket, key, str(p))
