FROM python:3.10-slim

WORKDIR /app

# Install poetry
RUN pip install poetry

COPY pyproject.toml poetry.lock* ./

# Configure poetry to not create virtualenvs
RUN poetry config virtualenvs.create false \
    && poetry install --no-dev --no-interaction --no-ansi

COPY . .

EXPOSE 5002

CMD ["uvicorn", "sim_service:app", "--host", "0.0.0.0", "--port", "5002"]
