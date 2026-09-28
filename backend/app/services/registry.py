"""Process-wide component registry (models, vector store). Selection is purely
configuration-driven so real models replace mocks without touching the API layer."""
from __future__ import annotations

import re
import threading
from functools import lru_cache

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.models import ModelRegistry
from app.models.base import ModelInfo
from app.models.change_model import (
    BaseChangeDetector,
    FeatureDifferenceChangeDetector,
    MockChangeDetector,
    NeuralChangeDetector,
)
from app.models.embedding_model import BaseEmbeddingModel, MockEmbeddingModel, RemoteSensingEmbeddingModel
from app.models.quality_model import BaseQualityModel, HeuristicQualityModel
from app.models.query_parser import BaseQueryParser, RuleBasedQueryParser
from app.models.reranker import BaseRanker, WeightedRanker
from app.vector.base import VectorStore

log = get_logger(__name__)
_lock = threading.Lock()


@lru_cache
def get_embedding_model() -> BaseEmbeddingModel:
    s = get_settings()
    if s.EMBEDDING_BACKEND == "remote_sensing":
        return RemoteSensingEmbeddingModel(
            s.EMBEDDING_MODEL_PATH, s.EMBEDDING_MODEL_NAME, s.EMBEDDING_MODEL_VERSION, s.EMBEDDING_DIMENSION,
            s.EMBEDDING_DEVICE, s.EMBEDDING_MODEL_LICENSE, s.EMBEDDING_MODEL_SOURCE)
    return MockEmbeddingModel(s.EMBEDDING_MODEL_NAME, s.EMBEDDING_MODEL_VERSION, s.EMBEDDING_DIMENSION,
                              s.BAND_MAPPING)


@lru_cache
def get_quality_model() -> BaseQualityModel:
    s = get_settings()
    return HeuristicQualityModel(s.BAND_MAPPING, s.CLOUD_BRIGHTNESS_THRESHOLD, s.SHADOW_BRIGHTNESS_THRESHOLD,
                                 s.QUALITY_MIN_FOR_CHANGE, s.MIN_VALID_PIXEL_RATIO)


@lru_cache
def get_change_detector() -> BaseChangeDetector:
    s = get_settings()
    if s.CHANGE_BACKEND == "mock":
        return MockChangeDetector()
    if s.CHANGE_BACKEND == "neural":
        return NeuralChangeDetector(s.CHANGE_MODEL_PATH, s.BAND_MAPPING, s.EMBEDDING_DEVICE)
    return FeatureDifferenceChangeDetector(s.BAND_MAPPING, s.CHANGE_THRESHOLD, s.SEASONAL_TOLERANCE_DAYS,
                                           s.CHANGE_MODEL_VERSION)


@lru_cache
def get_ranker() -> BaseRanker:
    s = get_settings()
    return WeightedRanker({"semantic": s.SEMANTIC_WEIGHT, "quality": s.QUALITY_WEIGHT, "change": s.CHANGE_WEIGHT,
                           "metadata": s.METADATA_WEIGHT, "spatial": s.SPATIAL_WEIGHT,
                           "temporal": s.TEMPORAL_WEIGHT})


@lru_cache
def get_query_parser() -> BaseQueryParser:
    return RuleBasedQueryParser()


def vector_namespace(info: ModelInfo) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", f"{info.name}__{info.version}")


_stores: dict[str, VectorStore] = {}


def get_vector_store(model: BaseEmbeddingModel | None = None) -> VectorStore:
    """One index per (embedding model, version): vectors from different models never mix."""
    s = get_settings()
    model = model or get_embedding_model()
    ns = vector_namespace(model.info())
    with _lock:
        if ns not in _stores:
            if s.VECTOR_BACKEND == "qdrant":
                from app.vector.qdrant_store import QdrantVectorStore

                path = s.QDRANT_PATH or str(s.data_dir("index") / "qdrant")
                _stores[ns] = QdrantVectorStore(path, ns, model.embedding_dimension())
            else:
                from app.vector.faiss_store import FAISSVectorStore

                _stores[ns] = FAISSVectorStore(s.data_dir("index") / ns, model.embedding_dimension(),
                                               s.FAISS_INDEX_TYPE, s.FAISS_HNSW_M)
        return _stores[ns]


def active_models() -> list[ModelInfo]:
    return [get_embedding_model().info(), get_change_detector().info(), get_quality_model().info(),
            get_ranker().info(), get_query_parser().info()]


def sync_model_registry(db: Session) -> None:
    """Upsert active model metadata; deactivate other versions of the same type."""
    for info in active_models():
        row = db.scalar(select(ModelRegistry).where(ModelRegistry.model_name == info.name,
                                                    ModelRegistry.version == info.version))
        if row is None:
            row = ModelRegistry(model_name=info.name, version=info.version, type=info.type)
            db.add(row)
        row.local_path, row.checksum, row.license, row.source = info.local_path, info.checksum, info.license, info.source
        row.input_schema, row.output_schema, row.active = info.input_schema, info.output_schema, True
        db.flush()
        for other in db.scalars(select(ModelRegistry).where(ModelRegistry.type == info.type,
                                                            ModelRegistry.id != row.id)):
            other.active = False
    db.commit()


def reset_registry() -> None:
    for f in (get_embedding_model, get_quality_model, get_change_detector, get_ranker, get_query_parser):
        f.cache_clear()
    _stores.clear()
