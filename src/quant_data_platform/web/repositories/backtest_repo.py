from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import psycopg
from quant_data_platform.storage import postgres_connection
from quant_data_platform.web.presets import STRATEGY_PRESETS, StrategyPreset, StrategyPresetId, get_strategy_preset


@dataclass(frozen=True)
class FactorSnapshotRow:
    symbol: str
    trade_date: date
    liquidity_rank: int
    factors: dict[str, Decimal | None]


@dataclass(frozen=True)
class ExecutionPriceRow:
    symbol: str
    trade_date: date
    adjusted_open: Decimal | None


@dataclass(frozen=True)
class DailyCloseRow:
    symbol: str
    trade_date: date
    adjusted_close: Decimal | None


@dataclass(frozen=True)
class ReadinessStatus:
    ok: bool
    code: str
    detail: str
    checked_relations: tuple[str, ...] = ()


class BacktestRepository:
    NULL_LIQUIDITY_RANK = 1_000_000_000

    def calendar_query(self) -> str:
        return """
            select observation_date
            from stg.stg_benchmark_series
            where benchmark_name = 'SPY'
              and observation_date between %(start_date)s and %(end_date)s
            order by observation_date
        """

    def factor_query(self, preset: StrategyPreset) -> str:
        factor_columns = ", ".join(preset_factor.column for preset_factor in preset.factor_specs)
        return f"""
            select symbol, trade_date, liquidity_rank, {factor_columns}
            from mart.{preset.mart_table}
            where trade_date = any(%(signal_dates)s::date[])
            order by trade_date, liquidity_rank nulls last, symbol
        """

    def earliest_available_query(self, preset: StrategyPreset) -> str:
        required = " and ".join(f"{factor.column} is not null" for factor in preset.factor_specs)
        return f"""
            select min(trade_date) as earliest_trade_date
            from mart.{preset.mart_table}
            where {required}
        """

    def execution_price_query(self) -> str:
        return """
            select symbol, trade_date, coalesce(adjusted_open, open) as adjusted_open
            from stg.stg_daily_prices
            where symbol = any(%(symbols)s::text[])
              and trade_date = any(%(trade_dates)s::date[])
            order by trade_date, symbol
        """

    def daily_close_query(self) -> str:
        return """
            select symbol, trade_date, coalesce(adjusted_close, close) as adjusted_close
            from stg.stg_daily_prices
            where symbol = any(%(symbols)s::text[])
              and trade_date between %(start_date)s and %(end_date)s
            order by trade_date, symbol
        """

    def freshness_token_query(self, preset: StrategyPreset) -> str:
        return f"""
            select
                coalesce(
                    to_char(
                        greatest(
                            coalesce((select max(trade_date)::timestamp from mart.{preset.mart_table}), timestamp '1970-01-01'),
                            coalesce((select max(effective_as_of) from stg.stg_daily_prices), timestamp '1970-01-01'),
                            coalesce((select max(observation_date)::timestamp from stg.stg_benchmark_series where benchmark_name = 'SPY'), timestamp '1970-01-01')
                        ),
                        'YYYY-MM-DD"T"HH24:MI:SS'
                    ),
                    '1970-01-01T00:00:00'
                ) as freshness_token
        """

    def schema_probe_query(self) -> str:
        return """
            select schema_name
            from information_schema.schemata
            where schema_name = any(%(schema_names)s::text[])
            order by schema_name
        """

    def compute_factor_buffer_start(self, preset_id: StrategyPresetId, start_date: date) -> date:
        preset = get_strategy_preset(preset_id)
        if preset.lookback_days <= 0:
            return date(start_date.year, start_date.month, 1)
        return start_date - timedelta(days=preset.lookback_days)

    def required_relations(self, preset_id: StrategyPresetId | None = None) -> tuple[str, ...]:
        mart_relations = (
            (f"mart.{get_strategy_preset(preset_id).mart_table}",)
            if preset_id is not None
            else tuple(
                f"mart.{preset.mart_table}"
                for preset in STRATEGY_PRESETS.values()
            )
        )
        return (
            "stg.stg_daily_prices",
            "stg.stg_benchmark_series",
            *mart_relations,
        )

    def relation_probe_query(self, relation_name: str) -> str:
        return f"select 1 from {relation_name} limit 1"

    def classify_error(self, exc: Exception, preset_id: StrategyPresetId | None = None) -> ReadinessStatus:
        detail = self._compact_error_detail(exc)
        if isinstance(exc, psycopg.OperationalError):
            code = "database_unreachable"
        elif isinstance(exc, psycopg.errors.InvalidSchemaName):
            code = "missing_schema"
        elif isinstance(exc, psycopg.errors.UndefinedTable):
            code = "missing_relation"
        else:
            code = "database_error"
        return ReadinessStatus(
            ok=False,
            code=code,
            detail=detail,
            checked_relations=self.required_relations(preset_id),
        )

    def check_readiness(self, preset_id: StrategyPresetId | None = None) -> ReadinessStatus:
        required_relations = self.required_relations(preset_id)
        try:
            with postgres_connection() as conn, conn.cursor() as cur:
                cur.execute(self.schema_probe_query(), {"schema_names": ["mart", "stg"]})
                found_schemas = {row["schema_name"] for row in cur.fetchall()}
                missing_schemas = [schema_name for schema_name in ("mart", "stg") if schema_name not in found_schemas]
                if missing_schemas:
                    return ReadinessStatus(
                        ok=False,
                        code="missing_schema",
                        detail=f"필수 스키마가 없습니다: {', '.join(missing_schemas)}",
                        checked_relations=required_relations,
                    )
                for relation_name in required_relations:
                    try:
                        cur.execute(self.relation_probe_query(relation_name))
                        cur.fetchone()
                    except psycopg.Error as exc:
                        return ReadinessStatus(
                            ok=False,
                            code="missing_relation" if isinstance(exc, psycopg.errors.UndefinedTable) else "unqueryable_relation",
                            detail=f"{relation_name} 확인 실패: {self._compact_error_detail(exc)}",
                            checked_relations=required_relations,
                        )
        except psycopg.Error as exc:
            return self.classify_error(exc, preset_id)
        return ReadinessStatus(
            ok=True,
            code="ok",
            detail="backtest dependencies are ready",
            checked_relations=required_relations,
        )

    def _compact_error_detail(self, exc: Exception) -> str:
        return " ".join(str(exc).split())

    def normalize_liquidity_rank(self, value: Any) -> int:
        if value is None:
            return self.NULL_LIQUIDITY_RANK
        return int(value)

    def fetch_spy_calendar(self, start_date: date, end_date: date) -> list[date]:
        with postgres_connection() as conn, conn.cursor() as cur:
            cur.execute(self.calendar_query(), {"start_date": start_date, "end_date": end_date})
            return [row["observation_date"] for row in cur.fetchall()]

    def fetch_factor_rows(self, preset_id: StrategyPresetId, signal_dates: list[date]) -> list[FactorSnapshotRow]:
        if not signal_dates:
            return []
        preset = get_strategy_preset(preset_id)
        with postgres_connection() as conn, conn.cursor() as cur:
            cur.execute(self.factor_query(preset), {"signal_dates": signal_dates})
            rows = []
            for row in cur.fetchall():
                factors = {factor.column: row[factor.column] for factor in preset.factor_specs}
                rows.append(
                    FactorSnapshotRow(
                        symbol=row["symbol"],
                        trade_date=row["trade_date"],
                        liquidity_rank=self.normalize_liquidity_rank(row["liquidity_rank"]),
                        factors=factors,
                    )
                )
            return rows

    def fetch_earliest_available_trade_date(self, preset_id: StrategyPresetId) -> date | None:
        preset = get_strategy_preset(preset_id)
        with postgres_connection() as conn, conn.cursor() as cur:
            cur.execute(self.earliest_available_query(preset))
            row = cur.fetchone()
            return row["earliest_trade_date"] if row else None

    def fetch_execution_prices(self, symbols: list[str], trade_dates: list[date]) -> list[ExecutionPriceRow]:
        if not symbols or not trade_dates:
            return []
        with postgres_connection() as conn, conn.cursor() as cur:
            cur.execute(self.execution_price_query(), {"symbols": symbols, "trade_dates": trade_dates})
            return [
                ExecutionPriceRow(
                    symbol=row["symbol"],
                    trade_date=row["trade_date"],
                    adjusted_open=row["adjusted_open"],
                )
                for row in cur.fetchall()
            ]

    def fetch_daily_closes(self, symbols: list[str], start_date: date, end_date: date) -> list[DailyCloseRow]:
        if not symbols:
            return []
        with postgres_connection() as conn, conn.cursor() as cur:
            cur.execute(self.daily_close_query(), {"symbols": symbols, "start_date": start_date, "end_date": end_date})
            return [
                DailyCloseRow(
                    symbol=row["symbol"],
                    trade_date=row["trade_date"],
                    adjusted_close=row["adjusted_close"],
                )
                for row in cur.fetchall()
            ]

    def fetch_freshness_token(self, preset_id: StrategyPresetId) -> str:
        preset = get_strategy_preset(preset_id)
        with postgres_connection() as conn, conn.cursor() as cur:
            cur.execute(self.freshness_token_query(preset))
            row = cur.fetchone()
            return row["freshness_token"] if row else "1970-01-01T00:00:00"
