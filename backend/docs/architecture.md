# Architecture

## Layering

| Layer | Package | Responsibility |
|---|---|---|
| API | `app/api/routes` | HTTP, validation (Pydantic v2), background-vs-sync dispatch. No business logic. |
| Schemas | `app/schemas` | Request/response contracts (OpenAPI). |
| Services | `app/services/*` | Business logic: ingestion, retrieval orchestration, change engine, discovery, review/feedback, provenance, export, index maintenance, quality facade. |
| Repositories | `app/repositories` | SQL access patterns (batched `IN` queries, paging). |
| Database | `app/db` | ORM entities, portable geometry type, sessions. |
| Geospatial | `app/geo` | All GDAL/Rasterio/pyproj code: validation, metadata, grid tiling, normalisation, alignment, thumbnails, spectral descriptors. |
| ML | `app/models` | Pluggable models with a common `ModelInfo`: embedding, quality, change, reranker, query parser. |
| Vector | `app/vector` | `VectorStore` contract, FAISS + Qdrant implementations, PostGIS metadata filter. |
| Storage | `app/storage` | `StorageBackend` (local FS, MinIO) — keys, never hard-coded paths. |
| Workers | `app/workers` | Job abstraction + handlers (local threads / sync / Celery). |

`app/services/registry.py` is the only place that chooses concrete implementations, driven by
settings. Everything else depends on the abstract base classes.

## Data plane (ingestion)

```
GeoTIFF/COG ─► validate (driver, CRS, geotransform) ─► sha256 ─► duplicate? ──yes──► return existing
                                                                   │no
      metadata: CRS, bounds, res, bands, time/sensor/platform (tags → STAC sidecar → filename → overrides)
                                                                   │
      scene row (status=processing) + provenance ◄─────────────────┘
                                                                   │
      grid-aligned windows (tile = TILE_SIZE px, grid anchored at CRS origin → stable location_key)
          for each window: boundless read → valid mask → skip if mostly nodata
                           → reflectance normalise (scene-level scale) → QualityModel.assess
                           → write tile COG + class mask + PNG thumbnail
                           → tile row + temporal_observation row + provenance
          every EMBEDDING_BATCH_SIZE tiles: encode → vector backup (.npz) → index.add
                           → embedding rows → COMMIT → index.save
      scene aggregates, status=complete, provenance
```

**Idempotency.** `scene_id = scn_<sha256[:20]>` and `checksum` is unique. Re-ingesting a completed
scene returns it. A failed/interrupted scene resumes: existing tiles are skipped and only missing
embeddings are produced. `EmbeddingIndexService.add_tile_vectors` checks the DB per (tile, model,
version) and removes index orphans for those tiles before adding, so vectors are never duplicated.

**Crash consistency.** The DB is authoritative. Vector ids are committed to the DB before the index
is saved; on startup `reconcile()` restores any committed-but-unsaved vectors from their `.npz`
backups and deletes index entries the DB doesn't know. Search maps ANN ids through the DB, so an
orphan can never surface as a result.

**Incremental.** `discover()` compares `(size, mtime)` stored at ingest time to skip unchanged files
without re-hashing; new or modified files are ingested and their vectors *appended*. The index is
only rebuilt on explicit request.

## Retrieval (two-stage)

**Stage 1 — cheap candidates.**
- If any filter is present, PostGIS counts matching tiles. When that count ≤ `FILTER_FIRST_THRESHOLD`,
  the matching vector ids are scored exactly (filter-first; exact recall under selective filters).
- Otherwise ANN-first: fetch `top_k × ANN_OVERSAMPLE`, map ids → tiles through the DB, apply
  `ST_Intersects` + time/sensor/platform/quality/cloud filters, and widen k ×4 until the pool is full
  or `ANN_MAX_CANDIDATES` is reached.

FAISS never sees geography; all metadata filtering is SQL.

**Stage 2 — expensive, bounded.**
- Component scores per candidate: semantic (cosine), quality, metadata compatibility (sensor/platform,
  cloud, valid pixels, and *context* evidence, e.g. "near a river" → tile water fraction),
  spatial (AOI overlap), temporal (recency within the window when the query has temporal intent).
- `require_change=true`: only the top `MAX_CHANGE_CANDIDATES` locations go through the temporal
  change engine; candidates without a verified change, or observed before its onset, are dropped.
- `WeightedRanker` combines the *applicable* components with configured weights, renormalised, and
  applies an optional feedback penalty for repeatedly rejected tiles.
- Results are grouped by location (one row per place) unless `group_by_location=false`.
- Query, results, scores and provenance are persisted; results can be re-read, reviewed and exported.

## Change engine

```
AOI → temporal_observation rows (PostGIS) → group by location_key → sort by time
    → QUALITY GATE (usable_for_change & quality ≥ min_quality)   ← before any differencing
    → reference = best-quality early observation
    → pairs (ref, later obs), capped at CHANGE_MAX_PAIRS_PER_LOCATION
    → align (reproject if grids differ) → detector.compare → temporal consensus → confidence
```

`FeatureDifferenceChangeDetector.compare` (per pair):

1. **Common clear pixels** — both masks clear (no cloud, haze, snow, shadow, nodata, saturation).
2. **Registration** — FFT phase correlation; an integer correction is applied *only if* it reduces the
   residual (new structures can create spurious peaks). Uncorrectable large shifts → `registration_factor` 0.3.
3. **Relative radiometric normalisation** — per-band gain/offset fitted on pseudo-invariant pixels
   (least-changed half). Removes illumination, haze residue and sensor gain differences.
4. **Differences** — ΔNDVI, ΔNDWI, Δbrightness, Δedge density, spectral RMS; changed pixels need
   majority support in their 4-neighbourhood (speckle removal).
5. **Typing** — rules over deltas + class-fraction changes (water, built-up, linearity) → construction,
   clearance, water_extent_change (+direction), road_development, appearance/disappearance,
   expansion/contraction, unknown.
6. **Pair-level suppression factors** — illumination, seasonal vegetation (uniform NDVI shift without
   structural change, stronger when day-of-year differs), sensor mismatch, viewing geometry
   (off-nadir, sun elevation), coverage.

Temporal consensus (per location):

```
onset          = earliest flagged observation followed by ≥50 % flagged observations
persistence    = flagged / observations since onset
tcf            = persistence · min(1, 0.55 + 0.15·n_supporting)
                 · (0.5 + 0.5·q)  if only one supporting observation
                 · 0.5            if transient
confidence     = base_change_score · quality_factor · registration_factor · tcf · (0.7 + 0.3·type_agreement)
```

`earliest_supported_time` is the onset observation; `last_unchanged_time` brackets it from below.
A cloudy acquisition in between is gated out, so the report is honest about *supported* evidence.
All factors are stored in `change_analysis.factors_json` and every compared pair in `change_evidence`.

## Provenance

`provenance_record` is an append-only log keyed by (entity_type, entity_id) with a `parent_entity`
edge. Records are written for: scene ingest and completion, each tile (tiling/quality parameters),
each embedding (model, version, checksum, vector id), each search query and result (weights, scores,
rank), and each change analysis (model, version, threshold, evidence tiles). `GET /provenance/...`
walks result → tile → scene (and change → evidence tiles → scenes) and returns original file paths,
checksums, processing steps, model versions and parameters. Exports embed it per feature/row.

## Database

PostgreSQL 16 + PostGIS 3. Geometries are `geometry(POLYGON,4326)` with GiST indexes; every spatial
table also carries `min_x/min_y/max_x/max_y` (B-tree composite index) for a cheap prefilter and for
the SQLite fallback. B-tree/composite indexes cover acquisition time, sensor(+time), scene, quality,
location_key(+time), change type(+confidence), review status, and job status. Datetimes are stored
timezone-aware in UTC. Schema is managed by Alembic (`0001_initial`).

## Jobs

`JobManager.submit(type, params)` persists a `job` row and hands the id to a backend:
`LocalJobBackend` (thread pool, default, no Redis), `SyncJobBackend` (tests/CLI), or
`CeleryJobBackend` (optional). Handlers are registered in `app/workers/*_worker.py`
(`ingest_scene`, `ingest_batch`, `ingest_incremental`, `change_analyze`, `reconcile_index`,
`rebuild_index`). Progress is written back to the row. On startup, jobs left running by a crash are
marked failed; resubmitting resumes idempotently.

## Scaling notes

- Switch `FAISS_INDEX_TYPE=hnsw` beyond ~1–5 M vectors, or move to Qdrant.
- Clustering reservoir-samples at most `CLUSTER_MAX_POINTS` and reads vectors in
  `CLUSTER_BATCH_SIZE` chunks; k-means uses `MiniBatchKMeans.partial_fit`.
- Change analysis loads only the tiles of candidate locations, cached per request.
- Run several API replicas only with `VECTOR_BACKEND=qdrant` (FAISS files are per-process); keep one
  writer for FAISS deployments.
