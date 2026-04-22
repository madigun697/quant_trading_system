from __future__ import annotations

import pendulum

from airflow.decorators import dag, task
from airflow.operators.bash import BashOperator

from quant_data_platform.pipeline import ingest_alpha_vantage_listing_status, run_daily_incremental


PROJECT_ROOT = "/opt/airflow/project"
DBT_PROFILES_DIR = "/opt/airflow/project/dbt"


@dag(
    dag_id="daily_incremental_pipeline",
    start_date=pendulum.datetime(2024, 1, 1, tz="America/New_York"),
    schedule="30 19 * * 1-5",
    catchup=False,
    tags=["incremental", "daily"],
)
def build_daily_incremental_pipeline() -> None:
    @task
    def refresh_listing_status() -> int:
        return ingest_alpha_vantage_listing_status()

    @task
    def ingest_sources() -> dict[str, dict[str, int]]:
        return run_daily_incremental()

    dbt_staging = BashOperator(
        task_id="dbt_staging",
        bash_command=f"cd {PROJECT_ROOT} && dbt run --project-dir dbt --profiles-dir {DBT_PROFILES_DIR} --select tag:stg tag:int",
    )

    dbt_marts = BashOperator(
        task_id="dbt_marts",
        bash_command=f"cd {PROJECT_ROOT} && dbt run --project-dir dbt --profiles-dir {DBT_PROFILES_DIR} --select tag:mart",
    )

    dbt_tests = BashOperator(
        task_id="dbt_tests",
        bash_command=f"cd {PROJECT_ROOT} && dbt test --project-dir dbt --profiles-dir {DBT_PROFILES_DIR}",
    )

    listing_status = refresh_listing_status()
    ingested = ingest_sources()

    listing_status >> ingested >> dbt_staging >> dbt_marts >> dbt_tests


build_daily_incremental_pipeline()
