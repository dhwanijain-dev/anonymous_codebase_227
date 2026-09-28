"""ORM entities. Public identifiers (scene_id, tile_id, analysis_id, …) are stable
string IDs used across the API, vector map and exports; integer `id` is internal."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, Geometry, UTCDateTime, utcnow


class BBoxMixin:
    """Denormalised bbox (EPSG:4326) for portable, index-friendly prefiltering."""

    min_x: Mapped[float | None] = mapped_column(Float)
    min_y: Mapped[float | None] = mapped_column(Float)
    max_x: Mapped[float | None] = mapped_column(Float)
    max_y: Mapped[float | None] = mapped_column(Float)

    @property
    def bbox(self) -> list[float] | None:
        if self.min_x is None:
            return None
        return [self.min_x, self.min_y, self.max_x, self.max_y]


class Scene(BBoxMixin, Base):
    __tablename__ = "scene"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scene_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    source_path: Mapped[str] = mapped_column(Text, nullable=False)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    sensor: Mapped[str | None] = mapped_column(String(64))
    platform: Mapped[str | None] = mapped_column(String(64))
    acquisition_time: Mapped[datetime | None] = mapped_column(UTCDateTime)
    processing_level: Mapped[str | None] = mapped_column(String(32))
    crs: Mapped[str | None] = mapped_column(String(128))
    resolution: Mapped[float | None] = mapped_column(Float)
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    bands: Mapped[int] = mapped_column(Integer)
    geometry: Mapped[str | None] = mapped_column(Geometry("POLYGON"))
    cloud_percentage: Mapped[float | None] = mapped_column(Float)
    quality_score: Mapped[float | None] = mapped_column(Float)
    checksum: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    ingestion_timestamp: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)

    tiles: Mapped[list[Tile]] = relationship(back_populates="scene", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_scene_acq", "acquisition_time"),
        Index("ix_scene_sensor", "sensor"),
        Index("ix_scene_platform", "platform"),
        Index("ix_scene_status", "status"),
        Index("ix_scene_sensor_acq", "sensor", "acquisition_time"),
        Index("ix_scene_bbox", "min_x", "min_y", "max_x", "max_y"),
    )


class Tile(BBoxMixin, Base):
    __tablename__ = "tile"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tile_id: Mapped[str] = mapped_column(String(96), unique=True, nullable=False)
    scene_id: Mapped[str] = mapped_column(ForeignKey("scene.scene_id", ondelete="CASCADE"), nullable=False)
    geometry: Mapped[str | None] = mapped_column(Geometry("POLYGON"))
    x_index: Mapped[int] = mapped_column(Integer)
    y_index: Mapped[int] = mapped_column(Integer)
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    raster_path: Mapped[str] = mapped_column(Text)
    thumbnail_path: Mapped[str | None] = mapped_column(Text)
    mask_path: Mapped[str | None] = mapped_column(Text)
    quality_score: Mapped[float | None] = mapped_column(Float)
    cloud_percentage: Mapped[float | None] = mapped_column(Float)
    valid_pixel_percentage: Mapped[float | None] = mapped_column(Float)
    quality_json: Mapped[dict] = mapped_column(JSON, default=dict)
    # Grid cell key: groups tiles from different scenes covering the same ground.
    location_key: Mapped[str | None] = mapped_column(String(64))
    # Denormalised from scene for single-table candidate filtering.
    acquisition_time: Mapped[datetime | None] = mapped_column(UTCDateTime)
    sensor: Mapped[str | None] = mapped_column(String(64))
    platform: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    scene: Mapped[Scene] = relationship(back_populates="tiles")

    __table_args__ = (
        UniqueConstraint("scene_id", "x_index", "y_index", name="uq_tile_scene_xy"),
        Index("ix_tile_scene", "scene_id"),
        Index("ix_tile_acq", "acquisition_time"),
        Index("ix_tile_sensor_acq", "sensor", "acquisition_time"),
        Index("ix_tile_quality", "quality_score"),
        Index("ix_tile_location_acq", "location_key", "acquisition_time"),
        Index("ix_tile_bbox", "min_x", "min_y", "max_x", "max_y"),
    )


class Embedding(Base):
    __tablename__ = "embedding"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tile_id: Mapped[str] = mapped_column(ForeignKey("tile.tile_id", ondelete="CASCADE"), nullable=False)
    embedding_type: Mapped[str] = mapped_column(String(32), default="image")
    model_name: Mapped[str] = mapped_column(String(128))
    model_version: Mapped[str] = mapped_column(String(32))
    dimension: Mapped[int] = mapped_column(Integer)
    vector_id: Mapped[int] = mapped_column(Integer, nullable=False)
    vector_path: Mapped[str | None] = mapped_column(Text)  # raw .npy copy for rebuilds
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    __table_args__ = (
        UniqueConstraint("tile_id", "model_name", "model_version", "embedding_type", name="uq_emb_tile_model"),
        UniqueConstraint("model_name", "model_version", "vector_id", name="uq_emb_vector"),
        Index("ix_emb_tile", "tile_id"),
    )


class TemporalObservation(BBoxMixin, Base):
    __tablename__ = "temporal_observation"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tile_id: Mapped[str] = mapped_column(ForeignKey("tile.tile_id", ondelete="CASCADE"), unique=True)
    location_key: Mapped[str] = mapped_column(String(64))
    location: Mapped[str | None] = mapped_column(Geometry("POLYGON"))
    acquisition_time: Mapped[datetime | None] = mapped_column(UTCDateTime)
    scene_id: Mapped[str] = mapped_column(ForeignKey("scene.scene_id", ondelete="CASCADE"))
    quality_score: Mapped[float | None] = mapped_column(Float)
    usable_for_change: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (
        Index("ix_obs_loc_time", "location_key", "acquisition_time"),
        Index("ix_obs_time", "acquisition_time"),
        Index("ix_obs_bbox", "min_x", "min_y", "max_x", "max_y"),
    )


class ChangeAnalysis(BBoxMixin, Base):
    __tablename__ = "change_analysis"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    analysis_id: Mapped[str] = mapped_column(String(64), unique=True)
    request_id: Mapped[str | None] = mapped_column(String(64))  # groups detections of one request
    geometry: Mapped[str | None] = mapped_column(Geometry("POLYGON"))
    location_key: Mapped[str | None] = mapped_column(String(64))
    start_time: Mapped[datetime | None] = mapped_column(UTCDateTime)
    end_time: Mapped[datetime | None] = mapped_column(UTCDateTime)
    earliest_supported_time: Mapped[datetime | None] = mapped_column(UTCDateTime)
    change_type: Mapped[str] = mapped_column(String(32), default="unknown")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    quality_score: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(32), default="pending_review")
    model_name: Mapped[str] = mapped_column(String(128))
    model_version: Mapped[str] = mapped_column(String(32))
    factors_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    evidence: Mapped[list[ChangeEvidence]] = relationship(
        back_populates="analysis", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_ca_type_conf", "change_type", "confidence"),
        Index("ix_ca_status", "status"),
        Index("ix_ca_request", "request_id"),
        Index("ix_ca_created", "created_at"),
    )


class ChangeEvidence(Base):
    __tablename__ = "change_evidence"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    analysis_id: Mapped[str] = mapped_column(ForeignKey("change_analysis.analysis_id", ondelete="CASCADE"))
    before_tile_id: Mapped[str] = mapped_column(ForeignKey("tile.tile_id"))
    after_tile_id: Mapped[str] = mapped_column(ForeignKey("tile.tile_id"))
    before_time: Mapped[datetime | None] = mapped_column(UTCDateTime)
    after_time: Mapped[datetime | None] = mapped_column(UTCDateTime)
    evidence_score: Mapped[float] = mapped_column(Float)
    processing_metadata: Mapped[dict] = mapped_column(JSON, default=dict)

    analysis: Mapped[ChangeAnalysis] = relationship(back_populates="evidence")
    __table_args__ = (Index("ix_ce_analysis", "analysis_id"),)


class SearchQuery(Base):
    __tablename__ = "search_query"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    query_id: Mapped[str] = mapped_column(String(64), unique=True)
    query_text: Mapped[str | None] = mapped_column(Text)
    query_type: Mapped[str] = mapped_column(String(32))  # text | image | similar_site
    filters_json: Mapped[dict] = mapped_column(JSON, default=dict)
    parsed_json: Mapped[dict] = mapped_column(JSON, default=dict)
    embedding_model: Mapped[str | None] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    results: Mapped[list[SearchResult]] = relationship(back_populates="query", cascade="all, delete-orphan")
    __table_args__ = (Index("ix_sq_created", "created_at"),)


class SearchResult(Base):
    __tablename__ = "search_result"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    result_id: Mapped[str] = mapped_column(String(64), unique=True)
    query_id: Mapped[str] = mapped_column(ForeignKey("search_query.query_id", ondelete="CASCADE"))
    tile_id: Mapped[str] = mapped_column(ForeignKey("tile.tile_id"))
    change_analysis_id: Mapped[str | None] = mapped_column(String(64))
    semantic_score: Mapped[float] = mapped_column(Float, default=0.0)
    metadata_score: Mapped[float] = mapped_column(Float, default=0.0)
    quality_score: Mapped[float] = mapped_column(Float, default=0.0)
    change_score: Mapped[float] = mapped_column(Float, default=0.0)
    spatial_score: Mapped[float] = mapped_column(Float, default=0.0)
    temporal_score: Mapped[float] = mapped_column(Float, default=0.0)
    final_score: Mapped[float] = mapped_column(Float, default=0.0)
    rank: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="pending_review")

    query: Mapped[SearchQuery] = relationship(back_populates="results")
    __table_args__ = (
        Index("ix_sr_query_rank", "query_id", "rank"),
        Index("ix_sr_status", "status"),
        Index("ix_sr_final", "final_score"),
    )


class AnalystReview(Base):
    __tablename__ = "analyst_review"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    review_id: Mapped[str] = mapped_column(String(64), unique=True)
    query_id: Mapped[str | None] = mapped_column(String(64))
    result_id: Mapped[str] = mapped_column(String(64))  # search result_id or change analysis_id
    result_type: Mapped[str] = mapped_column(String(32), default="search_result")
    decision: Mapped[str] = mapped_column(String(16))
    comment: Mapped[str | None] = mapped_column(Text)
    analyst_id: Mapped[str] = mapped_column(String(128), default="anonymous")
    timestamp: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    context_json: Mapped[dict] = mapped_column(JSON, default=dict)  # snapshot of scores at review time

    __table_args__ = (
        Index("ix_ar_result", "result_id"),
        Index("ix_ar_query", "query_id"),
        Index("ix_ar_ts", "timestamp"),
        Index("ix_ar_decision", "decision"),
    )


class ProvenanceRecord(Base):
    __tablename__ = "provenance_record"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(32))
    entity_id: Mapped[str] = mapped_column(String(96))
    source_scene_id: Mapped[str | None] = mapped_column(String(64))
    source_path: Mapped[str | None] = mapped_column(Text)
    source_checksum: Mapped[str | None] = mapped_column(String(64))
    processing_step: Mapped[str] = mapped_column(String(64))
    preprocessing_version: Mapped[str | None] = mapped_column(String(32))
    embedding_model: Mapped[str | None] = mapped_column(String(128))
    embedding_version: Mapped[str | None] = mapped_column(String(32))
    change_model: Mapped[str | None] = mapped_column(String(128))
    change_model_version: Mapped[str | None] = mapped_column(String(32))
    parameters_json: Mapped[dict] = mapped_column(JSON, default=dict)
    parent_entity: Mapped[str | None] = mapped_column(String(160))  # "type:id" lineage edge
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    __table_args__ = (
        Index("ix_prov_entity", "entity_type", "entity_id"),
        Index("ix_prov_scene", "source_scene_id"),
    )


class ModelRegistry(Base):
    __tablename__ = "model_registry"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model_name: Mapped[str] = mapped_column(String(128))
    version: Mapped[str] = mapped_column(String(32))
    type: Mapped[str] = mapped_column(String(32))  # embedding | change | quality | reranker | parser
    local_path: Mapped[str | None] = mapped_column(Text)
    checksum: Mapped[str | None] = mapped_column(String(64))
    license: Mapped[str | None] = mapped_column(String(128))
    source: Mapped[str | None] = mapped_column(String(256))
    input_schema: Mapped[dict] = mapped_column(JSON, default=dict)
    output_schema: Mapped[dict] = mapped_column(JSON, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    registered_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    __table_args__ = (
        UniqueConstraint("model_name", "version", name="uq_model_version"),
        Index("ix_model_type_active", "type", "active"),
    )


class Job(Base):
    __tablename__ = "job"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[str] = mapped_column(String(64), unique=True)
    job_type: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="queued")  # queued|running|succeeded|failed|cancelled
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    params_json: Mapped[dict] = mapped_column(JSON, default=dict)
    result_json: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    __table_args__ = (Index("ix_job_status_created", "status", "created_at"),)


SPATIAL_INDEX_DDL = [
    "CREATE INDEX IF NOT EXISTS gix_scene_geom ON scene USING GIST (geometry)",
    "CREATE INDEX IF NOT EXISTS gix_tile_geom ON tile USING GIST (geometry)",
    "CREATE INDEX IF NOT EXISTS gix_obs_geom ON temporal_observation USING GIST (location)",
    "CREATE INDEX IF NOT EXISTS gix_ca_geom ON change_analysis USING GIST (geometry)",
]
