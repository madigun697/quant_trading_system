from __future__ import annotations

from airflow.models import Variable


def get_default_cohort() -> str:
    return Variable.get("default_cohort", default_var="us_liquidity_700_v1")


def get_default_buffer_cohort() -> str:
    return Variable.get("buffer_cohort", default_var="us_liquidity_900_buffer_v1")


def get_default_symbols() -> list[str]:
    raw_value = Variable.get("default_symbol_set", default_var="")
    return [symbol.strip() for symbol in raw_value.split(",") if symbol.strip()]


def get_default_ciks() -> list[str]:
    raw_value = Variable.get("default_cik_set", default_var="")
    return [cik.strip() for cik in raw_value.split(",") if cik.strip()]
