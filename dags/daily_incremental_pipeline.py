from __future__ import annotations

import pendulum

from airflow.decorators import dag, task
from airflow.operators.bash import BashOperator

from quant_data_platform.pipeline import ingest_alpha_vantage_listing_status, run_daily_incremental

from common import get_default_buffer_cohort, get_default_cohort


PROJECT_ROOT = "/opt/airflow/project"
DBT_PROFILES_DIR = "/opt/airflow/project/dbt"
DBT_BIN = "/home/airflow/.local/bin/dbt"


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
    def ingest_sources(cohort: str | None = None) -> dict[str, dict[str, int]]:
        return run_daily_incremental(cohort=cohort or get_default_cohort())

    dbt_staging = BashOperator(
        task_id="dbt_staging",
        bash_command=f"cd {PROJECT_ROOT} && {DBT_BIN} run --project-dir dbt --profiles-dir {DBT_PROFILES_DIR} --select tag:stg tag:int",
        env={
            "DBT_UNIVERSE_COHORT": "{{ dag_run.conf.get('cohort', '" + get_default_cohort() + "') if dag_run else '" + get_default_cohort() + "' }}",
            "DBT_BUFFER_COHORT": "{{ dag_run.conf.get('buffer_cohort', '" + get_default_buffer_cohort() + "') if dag_run else '" + get_default_buffer_cohort() + "' }}",
        },
    )

    dbt_marts = BashOperator(
        task_id="dbt_marts",
        bash_command=f"cd {PROJECT_ROOT} && {DBT_BIN} run --project-dir dbt --profiles-dir {DBT_PROFILES_DIR} --select tag:mart",
        env={
            "DBT_UNIVERSE_COHORT": "{{ dag_run.conf.get('cohort', '" + get_default_cohort() + "') if dag_run else '" + get_default_cohort() + "' }}",
            "DBT_BUFFER_COHORT": "{{ dag_run.conf.get('buffer_cohort', '" + get_default_buffer_cohort() + "') if dag_run else '" + get_default_buffer_cohort() + "' }}",
        },
    )

    dbt_tests = BashOperator(
        task_id="dbt_tests",
        bash_command=f"cd {PROJECT_ROOT} && {DBT_BIN} test --project-dir dbt --profiles-dir {DBT_PROFILES_DIR}",
        env={
            "DBT_UNIVERSE_COHORT": "{{ dag_run.conf.get('cohort', '" + get_default_cohort() + "') if dag_run else '" + get_default_cohort() + "' }}",
            "DBT_BUFFER_COHORT": "{{ dag_run.conf.get('buffer_cohort', '" + get_default_buffer_cohort() + "') if dag_run else '" + get_default_buffer_cohort() + "' }}",
        },
    )

    listing_status = refresh_listing_status()
    ingested = ingest_sources()

    listing_status >> ingested >> dbt_staging >> dbt_marts >> dbt_tests


build_daily_incremental_pipeline()
