# syntax=docker/dockerfile:1.6
# Simulation Service — FastAPI + camel-oasis :5002
# Build context = repo root (set via docker-compose) để uv truy cập được
# cả vendored/oasis (path dep) lẫn libs/ecosim-common.

# Python 3.11 vì vendored/oasis pin `python = ">=3.10.0,<3.13"` ở
# pyproject.toml — đừng nâng lên 3.13/3.14 cho đến khi upstream camel-oasis
# nâng range.
FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /uvx /usr/local/bin/

ENV UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_COMPILE_BYTECODE=1

WORKDIR /app

# Path deps phải có trước khi uv sync resolve.
COPY libs/ecosim-common /app/libs/ecosim-common
COPY vendored/oasis /app/vendored/oasis

# Cache layer cho deps (rất nặng — torch, transformers, sentence-transformers).
COPY apps/simulation/pyproject.toml apps/simulation/uv.lock /app/apps/simulation/
WORKDIR /app/apps/simulation
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# App code
COPY apps/simulation /app/apps/simulation
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

ENV PATH="/app/apps/simulation/.venv/bin:$PATH" \
    PYTHONPATH=/app/libs/ecosim-common/src:/app/vendored/oasis

EXPOSE 5002
CMD ["uvicorn", "sim_service:app", "--host", "0.0.0.0", "--port", "5002"]
