# syntax=docker/dockerfile:1.7-labs

FROM python:3.12-slim AS python-deps

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --upgrade pip uv

WORKDIR /app
COPY pyproject.toml uv.lock ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv export --frozen --format requirements.txt --output-file requirements.lock --no-emit-project \
    && uv pip install --system --requirement requirements.lock --no-cache-dir \
    && rm requirements.lock

FROM python:3.12-slim AS worker

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=python-deps /usr/local /usr/local

WORKDIR /app
COPY worker ./worker
COPY api ./api
COPY pyproject.toml uv.lock ./

CMD ["python", "-m", "worker.worker"]