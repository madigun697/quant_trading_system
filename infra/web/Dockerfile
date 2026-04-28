FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.8.15 /uv /uvx /bin/

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/usr/local

COPY pyproject.toml uv.lock ./
COPY src ./src
RUN uv sync --locked --no-dev

COPY dbt ./dbt
COPY .env.example ./

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "quant_data_platform.web.app:app", "--host", "0.0.0.0", "--port", "8000"]
