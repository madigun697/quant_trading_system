from __future__ import annotations

import pendulum

from airflow.decorators import dag, task

from quant_data_platform.pipeline import run_market_backfill

from common import get_default_buffer_cohort


@dag(
    dag_id="backfill_market_data",
    start_date=pendulum.datetime(2024, 1, 1, tz="America/New_York"),
    schedule=None,
    catchup=False,
    tags=["backfill", "market_data", "yfinance"],
)
def build_backfill_market_data() -> None:
    @task
    def backfill(
        cohort: str | None = None,
        full_universe: bool = False,
        stage: str | None = None,
        mode: str = "full",
        start_date: str | None = None,
        end_date: str | None = None,
        symbol_set: list[str] | None = None,
        request_budget: int | None = None,
        reset_cursor: bool = False,
        force_reload: bool = False,
    ) -> dict[str, int]:
        del force_reload
        return run_market_backfill(
            symbols=symbol_set,
            cohort=cohort or get_default_buffer_cohort(),
            full_universe=full_universe,
            stage=stage,
            mode=mode,
            start_date=pendulum.parse(start_date).date() if start_date else None,
            end_date=pendulum.parse(end_date).date() if end_date else None,
            request_budget=request_budget,
            reset_cursor=reset_cursor,
        )

    backfill()


build_backfill_market_data()
