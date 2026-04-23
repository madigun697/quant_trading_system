from __future__ import annotations

import pendulum

from airflow.decorators import dag, task

from quant_data_platform.pipeline import run_fundamental_backfill

from common import get_default_buffer_cohort


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
        cohort: str | None = None,
        mode: str = "full",
        stage: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        cik_set: list[str] | None = None,
        request_budget: int | None = None,
        force_reload: bool = False,
    ) -> dict[str, int]:
        del start_date
        return run_fundamental_backfill(
            ciks=cik_set,
            cohort=cohort or get_default_buffer_cohort(),
            mode=mode,
            stage=stage,
            as_of_date=pendulum.parse(end_date).date() if end_date else None,
            request_budget=request_budget,
            reset_cursor=force_reload,
        )

    backfill()


build_backfill_fundamentals()
