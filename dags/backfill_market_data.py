from __future__ import annotations

import pendulum

from airflow.decorators import dag, task

from quant_data_platform.pipeline import run_market_backfill


@dag(
    dag_id="backfill_market_data",
    start_date=pendulum.datetime(2024, 1, 1, tz="America/New_York"),
    schedule=None,
    catchup=False,
    tags=["backfill", "tiingo", "market_data"],
)
def build_backfill_market_data() -> None:
    @task
    def backfill(
        start_date: str | None = None,
        end_date: str | None = None,
        symbol_set: list[str] | None = None,
        force_reload: bool = False,
    ) -> dict[str, int]:
        del start_date, end_date
        del force_reload
        return run_market_backfill(symbols=symbol_set)

    backfill()


build_backfill_market_data()
