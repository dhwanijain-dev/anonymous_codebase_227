# Build on a connected machine, then `docker save eo-backend | gzip > eo-backend.tar.gz` and
# `docker load` on the air-gapped host. Nothing is downloaded at runtime.
FROM python:3.11-slim AS base
ARG INSTALL_ML=false
ARG INSTALL_OPTIONAL=false
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    DATA_ROOT=/data HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
RUN apt-get update && apt-get install -y --no-install-recommends libexpat1 curl && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements*.txt ./
RUN pip install -r requirements.txt \
 && if [ "$INSTALL_ML" = "true" ]; then pip install -r requirements-ml.txt; fi \
 && if [ "$INSTALL_OPTIONAL" = "true" ]; then pip install -r requirements-optional.txt; fi
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
COPY scripts ./scripts
COPY tests ./tests
RUN useradd -m -u 1000 eo && mkdir -p /data /models && chown -R eo /data /app
USER eo
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD curl -fs http://localhost:8000/health || exit 1
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1"]
