FROM python:3.10-slim

# Build context is repo root (set via docker-compose), so paths below are
# relative to EcoSim/. This Dockerfile consumes both apps/simulation/ (app code)
# and vendored/oasis/ (upstream camel-oasis package).

WORKDIR /app

# Pin Poetry 2.2.1 — match version sinh poetry.lock (xem comment header
# trong vendored/oasis/poetry.lock). Poetry 2.x dùng schema lock mới,
# Poetry 1.x đọc không đúng. Đồng thời 2.x đổi flag --no-dev → --without dev.
RUN pip install "poetry==2.2.1"

# Upstream camel-oasis — provides pyproject + poetry.lock + `oasis` package
COPY vendored/oasis /app/vendored/oasis

WORKDIR /app/vendored/oasis
# Pyproject vs poetry.lock của upstream camel-oasis bị drift content-hash
# (commit upstream chứa cả 2 nhưng không sync). Đồng thời range Python
# `<3.13` không tương thích với `unstructured==0.13.7` (yêu cầu <3.12) khi
# regen lock. Image build trên Python 3.10 → narrow range cho khớp lock
# rồi regen + install.
# Strip CR trên Windows host (autocrlf) — phòng trường hợp file chưa LF.
# pyproject không khai báo group dev → install main only, không cần flag.
RUN sed -i 's/\r$//' pyproject.toml poetry.lock \
    && sed -i 's/python = ">=3.10.0,<3.13"/python = ">=3.10.0,<3.12"/' pyproject.toml \
    && poetry config virtualenvs.create false \
    && poetry lock \
    && poetry install --no-interaction --no-ansi

# EcoSim simulation app code
COPY apps/simulation /app/apps/simulation

# EcoSim-only deps (not in upstream OASIS pyproject — keeps vendored/oasis/
# clean against upstream syncs). See requirements-extra.txt for the list
# and rationale (currently: keybert).
RUN pip install --no-cache-dir -r /app/apps/simulation/requirements-extra.txt

# libs/ecosim-common is bind-mounted at runtime via docker-compose.
# PYTHONPATH also set in docker-compose environment for clarity.
ENV PYTHONPATH=/app/libs/ecosim-common/src:/app/vendored/oasis

WORKDIR /app/apps/simulation

EXPOSE 5002

CMD ["uvicorn", "sim_service:app", "--host", "0.0.0.0", "--port", "5002"]
