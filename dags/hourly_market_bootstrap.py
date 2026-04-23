from __future__ import annotations

import pendulum

from airflow.decorators import dag, task

from quant_data_platform.pipeline import build_liquidity_universe, refresh_monthly_universe_snapshots, run_market_backfill
from quant_data_platform.storage import postgres_connection

from common import get_default_buffer_cohort, get_default_cohort


@dag(
    dag_id="hourly_market_bootstrap",
    start_date=pendulum.datetime(2024, 1, 1, tz="America/New_York"),
    schedule="0 * * * *",
    catchup=False,
    tags=["bootstrap", "hourly", "tiingo"],
)
def build_hourly_market_bootstrap() -> None:
    @task
    def ensure_universe(
        cohort: str | None = None,
        buffer_cohort: str | None = None,
    ) -> dict[str, int]:
        active_buffer = 0
        with postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select count(*)
                    from meta.universe_members
                    where cohort = %s
                      and is_active = true
                    """,
                    (buffer_cohort or get_default_buffer_cohort(),),
                )
                active_buffer = cur.fetchone()["count"]
        if active_buffer > 0:
            return {"buffer_ready": 1, "build_executed": 0}
        build_stats = build_liquidity_universe(
            cohort=cohort or get_default_cohort(),
            buffer_cohort=buffer_cohort or get_default_buffer_cohort(),
        )
        return {"buffer_ready": 1, "build_executed": 1, **build_stats}

    @task
    def backfill_chunk(
        cohort: str | None = None,
        request_budget: int = 50,
        start_date: str = "1960-01-01",
    ) -> dict[str, int]:
        return run_market_backfill(
            cohort=cohort or get_default_buffer_cohort(),
            mode="chunked",
            request_budget=request_budget,
            start_date=pendulum.parse(start_date).date(),
        )

    @task
    def refresh_snapshots_if_ready(backfill_stats: dict[str, int]) -> dict[str, int]:
        if backfill_stats.get("remaining_symbols", 1) > 0:
            return {"skipped": 1}
        return refresh_monthly_universe_snapshots(cohort=get_default_cohort(), buffer_cohort=get_default_buffer_cohort())

    universe = ensure_universe()
    stats = backfill_chunk()
    universe >> stats
    refresh_snapshots_if_ready(stats)


build_hourly_market_bootstrap()
