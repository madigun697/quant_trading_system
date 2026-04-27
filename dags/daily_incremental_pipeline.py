from __future__ import annotations

import logging
from datetime import UTC, date

import pendulum
from airflow.decorators import dag, task
from airflow.operators.bash import BashOperator
from airflow.models import DagRun

from quant_data_platform.pipeline import (
    run_market_backfill,
    refresh_monthly_universe_snapshots,
    run_fundamental_backfill,
    ingest_fred_series,
    ingest_sec_ticker_reference,
)
from quant_data_platform.db import fetch_active_fred_series as _fetch_fred_series
from quant_data_platform.storage import postgres_connection
from quant_data_platform.config import get_settings
from common import get_default_buffer_cohort, get_default_cohort

logger = logging.getLogger(__name__)

PROJECT_ROOT = "/opt/airflow/project"
DBT_PROFILES_DIR = "/opt/airflow/project/dbt"
DBT_BIN = "/home/airflow/.local/bin/dbt"


def notify_failure(context: dict) -> None:
    """DAG/태스크 실패 시 Slack 또는 이메일 알림."""
    ti = context.get("task_instance")
    dr: DagRun = context.get("dag_run") or {}
    task_id = ti.task_id if ti else "unknown"
    dag_obj = context.get("dag")
    dag_id = dag_obj.dag_id if dag_obj else "unknown"
    exec_date = dr.execution_date if hasattr(dr, "execution_date") else "unknown"

    msg = (
        f"Airflow 실패 알림\n"
        f"DAG: {dag_id}\n"
        f"Task: {task_id}\n"
        f"Execution: {exec_date}\n"
        f"State: failed"
    )
    logger.warning(msg)

    slack_url = (context.get("params") or {}).get("slack_webhook_url")
    if slack_url:
        try:
            import requests
            requests.post(slack_url, json={"text": msg}, timeout=10)
        except Exception:
            logger.exception("Slack 알림 실패")

    try:
        from airflow.utils.email import send_email
        send_email(
            to=(context.get("params") or {}).get("email", ["admin@example.com"]),
            subject=f"[Airflow] DAG {dag_id} 태스크 {task_id} 실패",
            html_content=f"<pre>{msg}</pre>",
        )
    except Exception:
        logger.exception("이메일 알림 실패")


@dag(
    dag_id="daily_incremental_pipeline",
    start_date=pendulum.datetime(2024, 1, 1, tz="America/New_York"),
    schedule="30 19 * * 1-5",
    catchup=False,
    tags=["incremental", "daily"],
    default_args={"owner": "quant-team", "retries": 1},
)
def build_daily_incremental_pipeline() -> None:
    cohort_param = (
        "{{ dag_run.conf.get('cohort', '" + get_default_cohort() + "') if dag_run else '" + get_default_cohort() + "' }}"
    )
    buffer_cohort_param = (
        "{{ dag_run.conf.get('buffer_cohort', '" + get_default_buffer_cohort() + "') if dag_run else '" + get_default_buffer_cohort() + "' }}"
    )

    @task
    def ingest_sec_reference() -> dict[str, int]:
        return ingest_sec_ticker_reference()

    @task
    def ingest_market_data(cohort: str) -> dict[str, int]:
        return run_market_backfill(cohort=cohort, mode="recent", end_date=date.today())

    @task
    def ingest_snapshots(cohort: str) -> dict[str, int]:
        return refresh_monthly_universe_snapshots(cohort=cohort)

    @task
    def ingest_fundamentals(cohort: str) -> dict[str, int]:
        return run_fundamental_backfill(
            cohort=cohort,
            mode="chunked",
            as_of_date=date.today(),
            request_budget=25,
        )

    @task
    def ingest_fred_data() -> dict[str, int]:
        settings = get_settings()
        with postgres_connection(settings) as conn:
            series_ids = _fetch_fred_series(conn)
        return ingest_fred_series(series_ids, settings=settings)

    # 모든 소스 태스크 분리 — 서로 독립이므로 병렬 실행 가능
    sec_ref = ingest_sec_reference()
    market_data = ingest_market_data(cohort=cohort_param)
    snapshots = ingest_snapshots(cohort=cohort_param)
    fundamentals = ingest_fundamentals(cohort=cohort_param)

    # sec_ref 완료 후 market/snapshots/fundamentals/fred 병렬 실행
    fred_data = ingest_fred_data()
    (sec_ref, market_data, snapshots, fundamentals) >> fred_data

    dbt_env = {
        "DBT_UNIVERSE_COHORT": cohort_param,
        "DBT_BUFFER_COHORT": buffer_cohort_param,
    }

    dbt_staging = BashOperator(
        task_id="dbt_staging",
        bash_command=(
            f"cd {PROJECT_ROOT} && "
            f"{DBT_BIN} run --project-dir dbt --profiles-dir {DBT_PROFILES_DIR} --select tag:stg tag:int"
        ),
        env=dbt_env,
        on_failure_callback=notify_failure,
    )

    dbt_marts = BashOperator(
        task_id="dbt_marts",
        bash_command=(
            f"cd {PROJECT_ROOT} && "
            f"{DBT_BIN} run --project-dir dbt --profiles-dir {DBT_PROFILES_DIR} --select tag:mart"
        ),
        env=dbt_env,
        on_failure_callback=notify_failure,
    )

    dbt_tests = BashOperator(
        task_id="dbt_tests",
        bash_command=(
            f"cd {PROJECT_ROOT} && "
            f"{DBT_BIN} test --project-dir dbt --profiles-dir {DBT_PROFILES_DIR}"
        ),
        env=dbt_env,
        on_failure_callback=notify_failure,
    )

    # fred 는 마지막 데이터 소스 — dbt 전에 반드시 완료
    fred_data >> dbt_staging >> dbt_marts >> dbt_tests


build_daily_incremental_pipeline()
