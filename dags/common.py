from __future__ import annotations

from airflow.models import Variable


def get_default_symbols() -> list[str]:
    raw_value = Variable.get("prototype_symbol_set", default_var="AAPL,MSFT,NVDA,SPY")
    return [symbol.strip() for symbol in raw_value.split(",") if symbol.strip()]


def get_default_ciks() -> list[str]:
    raw_value = Variable.get("prototype_cik_set", default_var="")
    return [cik.strip() for cik in raw_value.split(",") if cik.strip()]
