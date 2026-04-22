from __future__ import annotations

import pendulum

from airflow.decorators import dag, task

from quant_data_platform.pipeline import run_fundamental_backfill


@dag(
    dag_id="backfill_fundamentals",
    start_date=pendulum.datetime(2024, 1, 1, tz="America/New_York"),
    schedule=None,
    catchup=False,
    tags=["backfill", "sec", "fundamentals"],
)
def build_backfill_fundamentals() -> None:
    @task
    def backfill(
        start_date: str | None = None,
        end_date: str | None = None,
        cik_set: list[str] | None = None,
        force_reload: bool = False,
    ) -> dict[str, int]:
        del start_date, end_date
        del force_reload
        return run_fundamental_backfill(ciks=cik_set)

    backfill()


build_backfill_fundamentals()
