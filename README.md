# Drishti

Drishti is a geospatial intelligence assistant for searching, analysing, and monitoring
satellite imagery. It combines natural-language and image-based retrieval with verified
multi-temporal change detection, site discovery, quality assessment, analyst review, and
end-to-end provenance.

The project is designed for offline or air-gapped operation: the backend can index a local
GeoTIFF/COG archive without making runtime internet requests, while the frontend provides a
focused interface for exploring the main intelligence workflows.

## Demo

Video Demonstration: **[![Demo Video](public/assets/thumbnail.png)](https://youtu.be/IokJ73amCbc)**

## Highlights

- **Semantic search:** Find scenes using natural-language queries such as “newly built structures near a river”.
- **Image-to-image search:** Search for visually similar satellite scenes from a local image path or upload.
- **Change analysis:** Compare aligned observations over time, suppress cloud and quality artefacts, classify likely changes, and report the earliest supported time.
- **Discovery and clustering:** Find similar sites and group them geographically.
- **Quality engine:** Gate unreliable observations before they influence retrieval or change analysis.
- **Analyst review:** Confirm or reject candidates and record feedback for later evaluation.
- **Provenance and export:** Trace results back to source scenes and export search or change results as GeoJSON, JSON, or CSV.
- **Background jobs:** Run long ingestion and analysis tasks synchronously, locally in-process, or with optional Celery and Redis workers.

## Repository layout

```text
backend/     FastAPI API, geospatial processing, models, storage, workers, and tests
frontend/    Next.js Drishti interface and local interactive demo scenarios
backend/docs/ Architecture notes and API request/response examples
```

## Quick start

### Frontend demo

The frontend currently uses local demo scenarios and does not require the backend to render its
interactive examples.

```bash
cd frontend
pnpm install
pnpm dev
```

Open [http://localhost:3000](http://localhost:3000). The sidebar and demo panel provide examples
for semantic search, change analysis, quality assessment, discovery, and analyst review.

### Backend with Docker

The backend uses PostgreSQL/PostGIS and includes a local in-process job worker by default.

```bash
cd backend
cp .env.example .env
mkdir -p data/raw models
docker compose up -d --build
curl http://localhost:8000/api/v1/health/ready
```

Open the interactive API documentation at [http://localhost:8000/docs](http://localhost:8000/docs).
To generate the synthetic six-date demo archive, run:

```bash
docker compose exec api python scripts/make_demo_data.py
```

Optional Docker profiles provide Celery/Redis workers (`--profile celery`) and MinIO object
storage (`--profile minio`). See [backend/README.md](backend/README.md) for environment variables,
model integration, operations, and air-gapped deployment details.

### Backend locally

```bash
cd backend
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
export DATABASE_URL=sqlite:///eo.db
export DATA_ROOT=$PWD/data
alembic upgrade head
python scripts/make_demo_data.py
uvicorn app.main:app --reload
```

SQLite is supported for laptop development and tests. PostgreSQL/PostGIS is recommended for
spatial workloads.

## Architecture
[Architecture](/frontend/public/assets/github-architecutre.png)

The FastAPI routes expose the service contract, while the service layer coordinates ingestion,
retrieval, change detection, discovery, review, provenance, and export. FAISS is the default
vector backend, with Qdrant available through the same abstraction. Model implementations are
selected through configuration, so local mock models can be replaced with locally hosted remote
sensing models without changing the API contract.

More detail is available in [backend/docs/architecture.md](backend/docs/architecture.md) and
[backend/docs/api_examples.md](backend/docs/api_examples.md).

## Testing

Run the backend test suite with:

```bash
cd backend
pytest -q
```

The tests cover ingestion idempotency, filtered retrieval, image search, change detection,
quality gating, discovery, review and feedback, provenance, exports, and vector-index recovery.
