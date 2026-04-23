from __future__ import annotations

import re
from datetime import date, timedelta

ALLOWED_EXCHANGES = {
    "NYSE",
    "NASDAQ",
    "AMEX",
    "NYSE MKT",
    "NYSE AMERICAN",
}

BLOCKED_NAME_TERMS = (
    " ETF",
    " ETN",
    " TRUST",
    " FUND",
    " ADR",
    " DEPOSITARY",
    " PREFERRED",
    " WARRANT",
    " RIGHT",
    " UNIT",
)

BLOCKED_SYMBOL_SUFFIXES = ("W", "WS", "R", "RT", "U", "UN")
ALLOWED_SYMBOL_PATTERN = re.compile(r"^[A-Z0-9]+([./-][A-Z])?$")


def is_allowed_exchange(exchange: str | None) -> bool:
    if exchange is None:
        return False
    normalized = exchange.strip().upper()
    return normalized in ALLOWED_EXCHANGES


def is_common_stock_candidate(
    *,
    symbol: str | None,
    exchange: str | None,
    asset_type: str | None,
    entity_name: str | None,
) -> bool:
    if not symbol or not is_allowed_exchange(exchange):
        return False

    normalized_asset_type = (asset_type or "").strip().lower()
    if normalized_asset_type and normalized_asset_type not in {"stock", "common stock", "equity"}:
        return False

    upper_name = f" {(entity_name or '').upper()} "
    if any(term in upper_name for term in BLOCKED_NAME_TERMS):
        return False

    normalized_symbol = symbol.upper().strip()
    if not ALLOWED_SYMBOL_PATTERN.fullmatch(normalized_symbol):
        return False

    symbol_base = normalized_symbol.replace(".", "-").replace("/", "-")
    if "-" in symbol_base:
        suffix = symbol_base.rsplit("-", 1)[-1]
        if suffix in BLOCKED_SYMBOL_SUFFIXES:
            return False

    return True


def discovery_start_date(end_date: date, discovery_days: int) -> date:
    return end_date - timedelta(days=max(discovery_days * 2, discovery_days + 30))
