FROM python:3.10-slim

# Build context is repo root (set via docker-compose), so paths below are
# relative to EcoSim/. This Dockerfile consumes both apps/simulation/ (app code)
# and vendored/oasis/ (upstream camel-oasis package).

WORKDIR /app

RUN pip install poetry

# Upstream camel-oasis — provides pyproject + poetry.lock + `oasis` package
COPY vendored/oasis /app/vendored/oasis

WORKDIR /app/vendored/oasis
RUN poetry config virtualenvs.create false \
    && poetry install --no-dev --no-interaction --no-ansi

# EcoSim simulation app code
COPY apps/simulation /app/apps/simulation

# libs/ecosim-common is bind-mounted at runtime via docker-compose.
# PYTHONPATH also set in docker-compose environment for clarity.
ENV PYTHONPATH=/app/libs/ecosim-common/src:/app/vendored/oasis

WORKDIR /app/apps/simulation

EXPOSE 5002

CMD ["uvicorn", "sim_service:app", "--host", "0.0.0.0", "--port", "5002"]
