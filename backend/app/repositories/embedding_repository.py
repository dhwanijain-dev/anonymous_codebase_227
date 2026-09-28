from sqlalchemy import func, select

from app.db.models import Embedding
from app.repositories.base import Repository


class EmbeddingRepository(Repository):
    def for_tile(self, tile_id: str, model_name: str, model_version: str) -> Embedding | None:
        return self.db.scalar(select(Embedding).where(
            Embedding.tile_id == tile_id, Embedding.model_name == model_name,
            Embedding.model_version == model_version, Embedding.embedding_type == "image"))

    def tiles_with_embeddings(self, tile_ids: list[str], model_name: str, model_version: str) -> set[str]:
        out: set[str] = set()
        for s in range(0, len(tile_ids), 900):
            out |= set(self.db.scalars(select(Embedding.tile_id).where(
                Embedding.tile_id.in_(tile_ids[s:s + 900]), Embedding.model_name == model_name,
                Embedding.model_version == model_version)))
        return out

    def vector_map(self, vector_ids: list[int], model_name: str, model_version: str) -> dict[int, str]:
        out: dict[int, str] = {}
        for s in range(0, len(vector_ids), 900):
            rows = self.db.execute(select(Embedding.vector_id, Embedding.tile_id).where(
                Embedding.vector_id.in_(vector_ids[s:s + 900]), Embedding.model_name == model_name,
                Embedding.model_version == model_version))
            out.update({v: t for v, t in rows})
        return out

    def iter_all(self, model_name: str, model_version: str, batch: int = 5000):
        last = -1
        while True:
            rows = list(self.db.scalars(select(Embedding).where(
                Embedding.model_name == model_name, Embedding.model_version == model_version,
                Embedding.id > last).order_by(Embedding.id).limit(batch)))
            if not rows:
                return
            yield rows
            last = rows[-1].id

    def count(self, model_name: str, model_version: str) -> int:
        return int(self.db.scalar(select(func.count()).select_from(Embedding).where(
            Embedding.model_name == model_name, Embedding.model_version == model_version)) or 0)
