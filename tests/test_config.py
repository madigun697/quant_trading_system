from __future__ import annotations

from quant_data_platform.config import Settings


def test_postgres_dsn() -> None:
    settings = Settings(
        POSTGRES_DB="quant",
        POSTGRES_USER="user",
        POSTGRES_PASSWORD="pass",
        POSTGRES_HOST="localhost",
        POSTGRES_PORT=5432,
    )
    assert "dbname=quant" in settings.postgres_dsn
    assert "user=user" in settings.postgres_dsn
