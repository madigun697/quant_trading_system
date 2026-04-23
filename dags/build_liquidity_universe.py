from __future__ import annotations

import pendulum

from airflow.decorators import dag, task

from quant_data_platform.pipeline import build_liquidity_universe

from common import get_default_buffer_cohort, get_default_cohort


@dag(
    dag_id="build_liquidity_universe",
    start_date=pendulum.datetime(2024, 1, 1, tz="America/New_York"),
    schedule=None,
    catchup=False,
    tags=["universe", "liquidity", "builder"],
)
def build_liquidity_universe_dag() -> None:
    @task
    def build(
        cohort: str | None = None,
        buffer_cohort: str | None = None,
        buffer_size: int = 1500,
        target_size: int = 1000,
        discovery_days: int = 90,
        lookback_days: int = 60,
    ) -> dict[str, int]:
        return build_liquidity_universe(
            cohort=cohort or get_default_cohort(),
            buffer_cohort=buffer_cohort or get_default_buffer_cohort(),
            buffer_size=buffer_size,
            target_size=target_size,
            discovery_days=discovery_days,
            lookback_days=lookback_days,
        )

    build()


build_liquidity_universe_dag()
