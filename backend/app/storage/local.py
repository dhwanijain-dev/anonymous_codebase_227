from pathlib import Path

from app.storage.base import StorageBackend

SUBDIRS = ("raw", "scenes", "tiles", "thumbnails", "masks", "embeddings", "index", "exports", "logs", "uploads")


class LocalStorageBackend(StorageBackend):
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        for d in SUBDIRS:
            (self.root / d).mkdir(parents=True, exist_ok=True)

    def _p(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if self.root not in p.parents and p != self.root:
            raise ValueError(f"Key escapes storage root: {key}")
        return p

    def save(self, key: str, data: bytes) -> str:
        p = self._p(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(p)  # atomic
        return key

    def read(self, key: str) -> bytes:
        return self._p(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self._p(key).exists()

    def delete(self, key: str) -> None:
        self._p(key).unlink(missing_ok=True)

    def get_path(self, key: str) -> Path:
        p = self._p(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p
