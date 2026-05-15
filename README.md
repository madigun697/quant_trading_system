# Quant Data Platform

An open-source prototype for building a US equity research and backtesting data platform with free or low-cost data sources.

This project focuses on collecting market, fundamental, macro, and filing data; transforming it into point-in-time research marts; and exposing the results through Airflow, dbt, PostgreSQL, MinIO, and a FastAPI web interface.

> Research and educational use only. This repository does not provide investment advice or a production trading guarantee.

Korean documentation: [README.ko.md](README.ko.md)

## What It Does

- Ingests US equity data from SEC, Alpha Vantage, yfinance, Tiingo, and FRED
- Stores structured data in PostgreSQL and object data in MinIO
- Builds dbt staging, intermediate, and mart models for research and backtesting
- Maintains liquidity-based equity universes and support market symbols such as SPY
- Runs Airflow DAGs for backfills, universe construction, and daily incremental updates
- Provides a FastAPI web UI for backtest review, current portfolio review, and Alpaca paper-trading integration
- Includes mart coverage audit tooling to inspect data completeness before running research

## Architecture

```text
External APIs
  SEC / Alpha Vantage / yfinance / Tiingo / FRED
        |
        v
Python ingestion CLI and Airflow DAGs
        |
        v
PostgreSQL raw/meta tables + MinIO object storage
        |
        v
dbt staging and intermediate models
        |
        v
strategy marts, coverage audits, backtest web UI
```

Core runtime components:

- Python package: `quant_data_platform`
- CLI entry point: `quant-pipeline`
- Orchestration: Airflow DAGs under `dags/`
- Transform layer: dbt project under `dbt/`
- Web app: `quant_data_platform.web.app`
- Local infrastructure: `docker-compose.yml`

## Data Sources

- `Alpha Vantage`: listing status and symbol overview data
- `yfinance`: long-history market backfills, dividends, splits, and corporate-action context
- `Tiingo`: daily incremental price updates
- `SEC`: EDGAR submissions and company facts
- `FRED`: macro and risk-free-rate series
- `Alpaca`: optional paper-trading dashboard integration

## Requirements

- Docker and Docker Compose
- Python 3.12 or newer
- `uv`
- API credentials for the live data sources you plan to use

Copy the sample environment file and fill in local values:

```bash
cp .env.example .env
```

Required or commonly used values:

- `ALPHAVANTAGE_API_KEY`
- `TIINGO_API_KEY`
- `FRED_API_KEY`
- `SEC_USER_AGENT`, for example `Your Name your@email.com`
- `ALPACA_API_KEY` and `ALPACA_SECRET_KEY`, only for Alpaca paper trading
- `INFRA_HOST`, defaults to `localhost`
- `POSTGRES_PORT`, defaults to `55432`

Do not commit `.env` files or real credentials.

## Quick Start

Initialize the local infrastructure:

```bash
docker compose up --build airflow-init
docker compose up -d postgres minio pgadmin airflow-webserver airflow-scheduler
```

Service endpoints with the default `INFRA_HOST=localhost`:

- Airflow: <http://localhost:8080>
- MinIO API: <http://localhost:9000>
- MinIO Console: <http://localhost:9001>
- pgAdmin: <http://localhost:5050>
- PostgreSQL: `localhost:55432`

The pgAdmin login values come from:

- `PGADMIN_DEFAULT_EMAIL`
- `PGADMIN_DEFAULT_PASSWORD`

The PostgreSQL server is registered in pgAdmin as `quant-postgres`.

## Main CLI Commands

```bash
uv sync
uv run quant-pipeline build-universe
uv run quant-pipeline backfill-market --mode recent
uv run quant-pipeline backfill-fundamentals --mode full
uv run quant-pipeline sync-fred --series DGS3MO DGS10
uv run quant-pipeline daily-incremental
uv run quant-pipeline audit-mart-coverage --cohort us_liquidity_700_v1
```

For JSON audit output:

```bash
uv run quant-pipeline audit-mart-coverage --cohort us_liquidity_700_v1 --format json
```

## Airflow DAGs

- `backfill_market_data`
- `backfill_fundamentals`
- `daily_incremental_pipeline`
- `build_liquidity_universe`

Typical full-universe refresh sequence:

```bash
docker compose exec airflow-webserver airflow dags trigger backfill_fundamentals --conf '{"full_universe": true, "mode": "full"}'
docker compose exec airflow-webserver airflow dags trigger backfill_market_data --conf '{"full_universe": true, "mode": "recent"}'
docker compose exec airflow-webserver airflow dags trigger build_liquidity_universe
docker compose exec airflow-webserver airflow dags trigger daily_incremental_pipeline
```

Equivalent CLI path:

```bash
INFRA_HOST=localhost POSTGRES_PORT=55432 uv run quant-pipeline backfill-fundamentals --full-universe --mode full
INFRA_HOST=localhost POSTGRES_PORT=55432 uv run quant-pipeline backfill-market --full-universe --mode recent
```

## dbt Models

- `stg_*`: source normalization
- `int_*`: point-in-time fundamentals, total-return prices, and universe snapshots
- `mart_*`: strategy-specific backtest input marts

Current mart families include:

- `mart_value_quality_inputs`
- `mart_value_momentum_inputs`
- `mart_quality_lowvol_inputs`

`stg_daily_prices` prioritizes Tiingo rows when Tiingo and yfinance overlap on the same date.

## Backtest And Web UI

The recommended web path is Docker:

```bash
docker compose up -d postgres backtest-web
```

Default routes:

- Backtest UI: `http://${INFRA_HOST}:8000/backtest`
- Current bucket: `http://${INFRA_HOST}:8000/current_bucket`
- Alpaca paper trading: `http://${INFRA_HOST}:8000/alpaca`
- Health check: `http://${INFRA_HOST}:8000/healthz`

Local FastAPI run:

```bash
INFRA_HOST=localhost POSTGRES_PORT=55432 uv run uvicorn quant_data_platform.web.app:app --reload
```

Point the app at a remote infrastructure host by changing `INFRA_HOST` and, if needed, `POSTGRES_PORT`.

## Market Timing

The backtest engine includes market timing ideas documented in `references/mkt_timing_strategy.md`, including asymmetric moving-average and canary-asset signals. Use these options to simulate defensive behavior during market drawdowns.

## Testing

Run local tests:

```bash
uv run pytest
```

Run live integration tests after credentials are configured:

```bash
ALPHAVANTAGE_API_KEY=... \
TIINGO_API_KEY=... \
FRED_API_KEY=... \
SEC_USER_AGENT="Your Name your@email.com" \
uv run pytest -m integration
```

Validate Docker Compose configuration:

```bash
docker compose config
```

## Related Documentation

- [Agent Core](docs/agent-core.md)
- [Repository Guide](REPO_GUIDE.md)
- [Quant Strategy Documentation](research_report/quant_strategy_documentation_en.md)
- [Backtest Data Requirements](research_report/us_equity_backtest_data_requirements_en.md)
- [Quant Factor Research](research_report/us_equity_quant_factor_research_en.md)

## Public Repository Notes

- `.env`, local data volumes, backups, caches, and generated dbt/Airflow state are ignored.
- Keep API keys, broker credentials, personal account identifiers, and local database dumps out of commits.
- Backtest output is research evidence, not a forward-looking performance guarantee.
