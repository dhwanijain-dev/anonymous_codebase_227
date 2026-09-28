"""Central configuration. Every tunable lives here and is overridable via env / .env."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "EO Intelligence Platform"
    API_PREFIX: str = "/api/v1"
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"

    # Database: PostgreSQL+PostGIS in production; SQLite supported for tests / laptop mode.
    DATABASE_URL: str = "postgresql+psycopg2://eo:eo@localhost:5432/eo"

    # Storage
    STORAGE_BACKEND: str = "local"  # local | minio
    DATA_ROOT: Path = Path("/data")
    INCREMENTAL_SCAN_DIRS: list[str] = Field(default_factory=lambda: ["raw"])
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = ""
    MINIO_SECRET_KEY: str = ""
    MINIO_BUCKET: str = "eo"

    # Tiling
    TILE_SIZE: int = 256
    TILE_OVERLAP: int = 0
    THUMBNAIL_SIZE: int = 128
    MIN_VALID_PIXEL_RATIO: float = 0.2
    PREPROCESSING_VERSION: str = "preproc-1.0.0"
    # Reflectance scaling: None => auto (uint8 /255, uint16 /10000, float as-is)
    REFLECTANCE_SCALE: float | None = None
    # 1-based band indices for spectral roles. Missing roles are approximated.
    BAND_MAPPING: dict[str, int] = Field(default_factory=lambda: {"blue": 1, "green": 2, "red": 3, "nir": 4})
    TILE_FORMAT: str = "COG"  # COG | GTiff

    # Embeddings
    EMBEDDING_BACKEND: str = "mock"  # mock | remote_sensing
    EMBEDDING_MODEL_PATH: str = "/models/embedding/model.pt"
    EMBEDDING_MODEL_NAME: str = "mock-rs-embed"
    EMBEDDING_MODEL_VERSION: str = "1.0.0"
    EMBEDDING_DIMENSION: int = 256
    EMBEDDING_MODEL_LICENSE: str = "internal"
    EMBEDDING_MODEL_SOURCE: str = "local"
    EMBEDDING_DEVICE: str = "cpu"
    EMBEDDING_BATCH_SIZE: int = 32

    # Change detection
    CHANGE_BACKEND: str = "feature_difference"  # feature_difference | mock | neural
    CHANGE_MODEL_PATH: str = "/models/change/model.pt"
    CHANGE_MODEL_VERSION: str = "1.0.0"
    CHANGE_THRESHOLD: float = 0.15
    CHANGE_MIN_REPORT_CONFIDENCE: float = 0.2
    CHANGE_MAX_PAIRS_PER_LOCATION: int = 6
    SEASONAL_TOLERANCE_DAYS: int = 45
    MAX_CHANGE_CANDIDATES: int = 50  # stage-2 budget for search-with-change

    # Quality
    QUALITY_BACKEND: str = "heuristic"
    QUALITY_MIN_FOR_CHANGE: float = 0.5
    CLOUD_BRIGHTNESS_THRESHOLD: float = 0.75
    SHADOW_BRIGHTNESS_THRESHOLD: float = 0.08

    # Vector store
    VECTOR_BACKEND: str = "faiss"  # faiss | qdrant
    ANN_OVERSAMPLE: int = 10  # fetch top_k * oversample before metadata filtering
    ANN_MAX_CANDIDATES: int = 5000
    FILTER_FIRST_THRESHOLD: int = 20000  # if <= this many tiles match filters, score them exactly
    FAISS_INDEX_TYPE: str = "flat"  # flat | hnsw
    FAISS_HNSW_M: int = 32
    QDRANT_PATH: str = ""  # local on-disk qdrant; empty => DATA_ROOT/index/qdrant

    # Ranking weights (normalised at runtime)
    SEMANTIC_WEIGHT: float = 0.45
    QUALITY_WEIGHT: float = 0.15
    CHANGE_WEIGHT: float = 0.20
    METADATA_WEIGHT: float = 0.10
    SPATIAL_WEIGHT: float = 0.10
    TEMPORAL_WEIGHT: float = 0.0
    FEEDBACK_REJECT_PENALTY: float = 0.0  # 0 disables feedback-aware down-ranking

    # Discovery
    CLUSTER_BATCH_SIZE: int = 2048
    CLUSTER_MAX_POINTS: int = 50000
    CLUSTER_REPRESENTATIVES: int = 5

    # Jobs
    JOB_BACKEND: str = "local"  # local | celery | sync
    JOB_WORKERS: int = 2
    REDIS_URL: str = "redis://localhost:6379/0"

    # Security
    API_KEYS: list[str] = Field(default_factory=list)  # empty => auth disabled
    ALLOWED_INGEST_ROOTS: list[str] = Field(default_factory=list)  # empty => DATA_ROOT only

    @property
    def is_sqlite(self) -> bool:
        return self.DATABASE_URL.startswith("sqlite")

    def data_dir(self, name: str) -> Path:
        p = Path(self.DATA_ROOT) / name
        p.mkdir(parents=True, exist_ok=True)
        return p


@lru_cache
def get_settings() -> Settings:
    return Settings()
