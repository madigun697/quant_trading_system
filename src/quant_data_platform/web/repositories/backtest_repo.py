from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from quant_data_platform.storage import postgres_connection
from quant_data_platform.web.presets import StrategyPreset, StrategyPresetId, get_strategy_preset


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


class BacktestRepository:
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
            order by trade_date, liquidity_rank, symbol
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

    def compute_factor_buffer_start(self, preset_id: StrategyPresetId, start_date: date) -> date:
        preset = get_strategy_preset(preset_id)
        if preset.lookback_days <= 0:
            return date(start_date.year, start_date.month, 1)
        return start_date - timedelta(days=preset.lookback_days)

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
                        liquidity_rank=int(row["liquidity_rank"]),
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
