# EO Intelligence Platform — Backend

On-premises backend that makes a GeoTIFF/COG satellite archive searchable by natural language,
by example image, by space/time/sensor, and by **verified multi-temporal change** — with analyst
review and end-to-end provenance. Nothing calls the internet at runtime.

```
client ─► FastAPI ─► Query orchestrator ─┬─► semantic / image retrieval (FAISS ANN ⟷ PostGIS filters)
                                         └─► temporal change engine
                                   ─► quality gate ─► weighted reranker ─► provenance ─► results
```

See [`docs/architecture.md`](docs/architecture.md) for design details and
[`docs/api_examples.md`](docs/api_examples.md) for request/response walkthroughs.

---

## Quick start

### Docker (PostGIS + API, no Redis)

```bash
cp .env.example .env
mkdir -p data/raw models
cp /path/to/imagery/*.tif data/raw/
docker compose up -d --build
curl localhost:8000/api/v1/health/ready
curl -X POST localhost:8000/api/v1/ingestion/incremental -H 'content-type: application/json' -d '{}'
open http://localhost:8000/docs          # OpenAPI UI
```

Optional profiles: `--profile celery` (Redis + Celery worker, set `JOB_BACKEND=celery`) and
`--profile minio` (local S3-compatible storage, set `STORAGE_BACKEND=minio`).

### Local (no Docker)

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
export DATABASE_URL=postgresql+psycopg2://eo:eo@localhost:5432/eo DATA_ROOT=$PWD/data
alembic upgrade head
python scripts/make_demo_data.py            # synthetic 6-date series incl. a construction event + cloud
uvicorn app.main:app --reload
```

SQLite also works for laptops/tests (`DATABASE_URL=sqlite:///eo.db`); spatial filters then use the
denormalised bbox columns instead of `ST_Intersects`.

### Air-gapped deployment

1. On a connected machine: `docker compose build` (add `--build-arg INSTALL_ML=true` for PyTorch),
   then `docker save eo-backend postgis/postgis:16-3.4 | gzip > eo.tar.gz`.
2. Stage model folders under `models/` (see *Plugging in real models*).
3. On the target: `docker load < eo.tar.gz && docker compose up -d`.

`HF_HUB_OFFLINE=1` is set in the image; model loaders only ever read local paths.

---

## Tests

```bash
pytest -q                                                   # SQLite
TEST_DATABASE_URL=postgresql+psycopg2://eo:eo@localhost/eo_test pytest -q   # real PostGIS
```

The suite (23 tests) builds a synthetic multi-temporal archive with known ground truth and checks:
ingestion idempotency (no duplicate vectors on re-ingest/force), incremental ingest appending only
new vectors, filtered text search, image search (path + upload), similar-site discovery, clustering,
cloud gating before change detection, construction typing, earliest-supported-time, temporal
consensus (persistent ≫ transient ≫ flicker), illumination and misregistration suppression,
review/feedback, provenance completeness, all export formats, index recovery after a lost index,
path sandboxing and validation errors.

---

## API surface (`/api/v1`)

| Area | Endpoints |
|---|---|
| Health | `GET /health`, `GET /api/v1/health/ready` |
| Ingestion | `POST /ingestion/scene`, `POST /ingestion/batch`, `POST /ingestion/incremental`, `GET /ingestion/discover` |
| Scenes / tiles | `GET /scenes`, `GET /scenes/{id}`, `GET /scenes/{id}/tiles`, `DELETE /scenes/{id}`, `GET /tiles/{id}`, `GET /tiles/{id}/thumbnail`, `GET /tiles/{id}/raster?kind=data|mask` |
| Search | `POST /search/text`, `POST /search/image`, `POST /search/image/upload`, `GET /search/{query_id}` |
| Change | `POST /change/analyze`, `GET /change/{analysis_id}` |
| Discovery | `POST /discovery/similar-sites`, `POST /discovery/cluster` |
| Review | `POST /review`, `GET /review/queue`, `GET /review/history` |
| Feedback | `GET /feedback/statistics`, `GET /feedback/hard-negatives`, `GET /feedback/export` |
| Provenance | `GET /provenance/{entity_type}/{entity_id}` |
| Export | `GET /export/search/{query_id}?format=geojson|csv`, `GET /export/change/{analysis_id}?format=geojson|json|csv` |
| Models | `GET /models`, `GET /models/{model_name}` |
| Jobs | `GET /jobs`, `POST /jobs`, `GET /jobs/{id}`, `POST /jobs/{id}/cancel` |

Long operations accept `"background": true` and return a job; poll `GET /jobs/{job_id}`.
Set `API_KEYS=["..."]` to require an `X-API-Key` header.

---

## Plugging in real models

All model selection is configuration; APIs and the database schema do not change.

**Embeddings** (`EMBEDDING_BACKEND=remote_sensing`) — a folder with TorchScript exports, e.g. of
RemoteCLIP / GeoRSCLIP / SatCLIP / Prithvi:

```
models/embedding/
  image_encoder.pt      float[B,C,H,W] -> float[B,D]
  text_encoder.pt       optional: int64[B,T] -> float[B,D]
  tokenizer.json        optional (HF `tokenizers`, loaded from disk)
  model_card.json       {"name","version","license","source","dimension","input_size","bands","mean","std"}
```

Each (model, version) gets its **own** vector index namespace, so switching models never mixes
vector spaces. Populate the new index with `python scripts/build_index.py reembed`.

**Change detector** (`CHANGE_BACKEND=neural`) — TorchScript siamese network
`float[1,2C,H,W] -> (prob[1,1,H,W], type_logits[1,K])` + `model_card.json` with `change_types`.
It reuses the interpretable suppression factors and the temporal consensus engine unchanged.

**Quality** — implement `BaseQualityModel.assess(image, valid) -> (QualityResult, mask)`
(e.g. an exported cloud/shadow segmenter) and return it from `registry.get_quality_model`.

**Query parser** — implement `BaseQueryParser.parse(text) -> ParsedQuery` (e.g. a local llama.cpp
model emitting the same JSON).

**Vector store** — `VECTOR_BACKEND=qdrant` uses Qdrant in embedded/on-disk mode behind the same
`VectorStore` interface.

Registered model metadata (name, version, checksum, license, source, I/O schema) is synced into
`model_registry` at startup and exposed at `/api/v1/models`.

---

## Operations

| Task | Command |
|---|---|
| Ingest files/dirs | `python scripts/ingest.py /data/raw/2024/ --sensor MSI` |
| Incremental (cron) | `python scripts/incremental_ingest.py` (`--dry-run` lists new files) |
| Repair index vs DB | `python scripts/build_index.py reconcile` (also runs on every startup) |
| Rebuild index (e.g. flat→hnsw) | `FAISS_INDEX_TYPE=hnsw python scripts/build_index.py rebuild` |
| Re-embed with a new model | `python scripts/build_index.py reembed` |
| Evaluate retrieval | `python scripts/evaluate.py retrieval [--benchmark bench.jsonl]` |
| Evaluate change detection | `python scripts/evaluate.py change --truth truth.geojson --bbox ...` |

Data layout under `DATA_ROOT`: `raw/ scenes/ tiles/ thumbnails/ masks/ embeddings/ index/ exports/ logs/ uploads/`.

---

## Known limitations / next steps

- The mock embedding is a deterministic, physically-grounded descriptor space (spectral indices,
  texture, linearity) — useful for water/vegetation/built-up/road/bare-soil queries and for
  exercising the pipeline, but not a substitute for a trained vision-language model.
- The heuristic quality engine has no SWIR/thermal bands, so cloud/snow separation is approximate.
- Tiles are aligned to a CRS-anchored grid; observations in a different CRS or resolution are
  reprojected on the fly during change analysis, but are grouped by grid key, so mixed-CRS stacks of
  the same place should be warped to a common grid at ingestion for best results.
- SAR (Sentinel-1) ingests and indexes, but the optical quality/change heuristics do not apply to it.
- The job spec section of the original brief was truncated; the job system implements the
  requirements stated elsewhere (Redis-free local worker, optional Celery, persisted job state,
  crash recovery).
