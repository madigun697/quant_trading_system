from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_env_example_documents_local_uv_override() -> None:
    env_example = (REPO_ROOT / ".env.example").read_text()
    assert "# Local uv override example:" in env_example
    assert "# POSTGRES_HOST=127.0.0.1" in env_example
    assert "# POSTGRES_PORT=55432" in env_example


def test_docker_compose_uses_non_default_host_postgres_port() -> None:
    compose = (REPO_ROOT / "docker-compose.yml").read_text()
    assert '"55432:5432"' in compose


def test_readme_documents_docker_and_local_backtest_runs() -> None:
    readme = (REPO_ROOT / "README.md").read_text()
    assert "docker compose up -d postgres backtest-web" in readme
    assert "POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=55432 uv run uvicorn quant_data_platform.web.app:app --reload" in readme
