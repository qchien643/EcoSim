# syntax=docker/dockerfile:1.6
# Core Service — Flask :5001
# Build context = repo root (set via docker-compose) để uv truy cập được
# libs/ecosim-common ở build time (path dep trong pyproject.toml).

FROM python:3.14-slim

# Static uv binary từ image chính thức.
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /uvx /usr/local/bin/

ENV UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_COMPILE_BYTECODE=1

WORKDIR /app

# Path dep cần có trước khi uv sync resolve dep graph.
COPY libs/ecosim-common /app/libs/ecosim-common

# Cache layer cho deps: chỉ copy pyproject + lock trước, sync deps, rồi mới copy app code.
COPY apps/core/pyproject.toml apps/core/uv.lock /app/apps/core/
WORKDIR /app/apps/core
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# App code
COPY apps/core /app/apps/core
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

ENV PATH="/app/apps/core/.venv/bin:$PATH" \
    PYTHONPATH=/app/libs/ecosim-common/src

EXPOSE 5001
CMD ["python", "run.py"]
