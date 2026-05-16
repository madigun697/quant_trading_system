from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import psycopg
from psycopg.types.json import Jsonb
from quant_data_platform.config import get_settings
from quant_data_platform.storage import postgres_connection
from quant_data_platform.web.presets import STRATEGY_PRESETS, StrategyPreset, StrategyPresetId, get_strategy_preset

if TYPE_CHECKING:
    from quant_data_platform.web.schemas import BacktestFormInput, BacktestPageContext
    from quant_data_platform.web.services.engine import SimulationResult


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
class BenchmarkValueRow:
    observation_date: date
    value: Decimal | None


@dataclass(frozen=True)
class ReadinessStatus:
    ok: bool
    code: str
    detail: str
    checked_relations: tuple[str, ...] = ()


def _json_ready(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    return value


class BacktestRepository:
    NULL_LIQUIDITY_RANK = 1_000_000_000
    BACKTEST_RESULT_TABLE_SQL = (
        """
        create table if not exists mart.backtest_run_summary (
            run_id text primary key,
            created_at timestamptz not null default now(),
            start_date date not null,
            end_date date not null,
            strategy_preset text not null,
            market_timing_overlay text not null,
            safe_asset_summary text not null default '',
            initial_capital numeric not null,
            top_n integer not null,
            transaction_cost_preset text not null,
            final_gross_equity numeric,
            final_net_equity numeric,
            final_benchmark_equity numeric,
            gross_total_return numeric,
            net_total_return numeric,
            gross_cagr numeric,
            net_cagr numeric,
            max_drawdown_net numeric,
            sharpe numeric,
            trade_count integer not null default 0,
            win_rate numeric,
            expected_value numeric,
            turnover numeric,
            total_fees numeric,
            average_holding_period numeric,
            metrics jsonb not null default '{}'::jsonb,
            form_values jsonb not null default '{}'::jsonb,
            config jsonb not null default '{}'::jsonb,
            warnings jsonb not null default '[]'::jsonb,
            data_quality_flags jsonb not null default '[]'::jsonb
        )
        """,
        """
        create table if not exists mart.backtest_equity_curve (
            id bigserial primary key,
            run_id text not null references mart.backtest_run_summary(run_id) on delete cascade,
            equity_date date not null,
            gross_equity numeric not null,
            net_equity numeric not null,
            benchmark_equity numeric,
            details jsonb not null default '{}'::jsonb,
            created_at timestamptz not null default now(),
            unique (run_id, equity_date)
        )
        """,
        """
        create table if not exists mart.backtest_rebalance_summary (
            id bigserial primary key,
            run_id text not null references mart.backtest_run_summary(run_id) on delete cascade,
            signal_date date not null,
            execution_date date not null,
            selected_count integer not null,
            sold_count integer not null,
            buy_notional numeric not null,
            sell_notional numeric not null,
            fees numeric not null,
            turnover numeric not null,
            notes text,
            details jsonb not null default '{}'::jsonb,
            created_at timestamptz not null default now()
        )
        """,
        """
        create table if not exists mart.backtest_fill_log (
            id bigserial primary key,
            run_id text not null references mart.backtest_run_summary(run_id) on delete cascade,
            execution_date date not null,
            signal_date date not null,
            symbol text not null,
            action text not null,
            shares numeric not null,
            execution_price numeric not null,
            fees numeric not null,
            net_cash_flow numeric not null,
            realized_pnl numeric,
            holding_days integer,
            details jsonb not null default '{}'::jsonb,
            created_at timestamptz not null default now()
        )
        """,
    )

    def calendar_query(self) -> str:
        return """
            select observation_date
            from stg.stg_benchmark_series
            where benchmark_name = 'SPY'
              and observation_date between %(start_date)s and %(end_date)s
            order by observation_date
        """

    def benchmark_value_query(self) -> str:
        return """
            select observation_date, value
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

    def ensure_backtest_result_tables(self) -> None:
        with postgres_connection() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    for statement in self.BACKTEST_RESULT_TABLE_SQL:
                        cur.execute(statement)

    @staticmethod
    def generate_run_id(created_at: datetime | None = None) -> str:
        actual_created_at = created_at or datetime.now(timezone.utc)
        if actual_created_at.tzinfo is None:
            actual_created_at = actual_created_at.replace(tzinfo=timezone.utc)
        return f"bt-{actual_created_at.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}"

    def save_simulation_result(
        self,
        *,
        form: "BacktestFormInput",
        context: "BacktestPageContext",
        simulation: "SimulationResult",
        run_id: str | None = None,
        created_at: datetime | None = None,
    ) -> dict[str, Any]:
        actual_created_at = created_at or datetime.now(timezone.utc)
        actual_run_id = run_id or self.generate_run_id(actual_created_at)
        final_point = simulation.equity_curve[-1] if simulation.equity_curve else None
        metrics = simulation.summary_metrics
        warnings = [warning.model_dump() for warning in context.warnings]
        config = {
            "strategy_preset": form.strategy_preset.value,
            "market_timing_overlay": form.market_timing_overlay.value,
            "safe_asset_allocations": [
                {"symbol": symbol.value, "weight": float(weight)}
                for symbol, weight in form.safe_asset_allocations()
            ],
            "initial_capital": float(form.initial_capital),
            "top_n": form.top_n,
            "transaction_cost_preset": form.transaction_cost_preset.value,
        }
        with postgres_connection() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    for statement in self.BACKTEST_RESULT_TABLE_SQL:
                        cur.execute(statement)
                    cur.execute("delete from mart.backtest_run_summary where run_id = %(run_id)s", {"run_id": actual_run_id})
                    cur.execute(
                        """
                        insert into mart.backtest_run_summary (
                            run_id, created_at, start_date, end_date, strategy_preset, market_timing_overlay,
                            safe_asset_summary, initial_capital, top_n, transaction_cost_preset,
                            final_gross_equity, final_net_equity, final_benchmark_equity,
                            gross_total_return, net_total_return, gross_cagr, net_cagr, max_drawdown_net,
                            sharpe, trade_count, win_rate, expected_value, turnover, total_fees,
                            average_holding_period, metrics, form_values, config, warnings, data_quality_flags
                        ) values (
                            %(run_id)s, %(created_at)s, %(start_date)s, %(end_date)s, %(strategy_preset)s,
                            %(market_timing_overlay)s, %(safe_asset_summary)s, %(initial_capital)s, %(top_n)s,
                            %(transaction_cost_preset)s, %(final_gross_equity)s, %(final_net_equity)s,
                            %(final_benchmark_equity)s, %(gross_total_return)s, %(net_total_return)s,
                            %(gross_cagr)s, %(net_cagr)s, %(max_drawdown_net)s, %(sharpe)s, %(trade_count)s,
                            %(win_rate)s, %(expected_value)s, %(turnover)s, %(total_fees)s,
                            %(average_holding_period)s, %(metrics)s::jsonb, %(form_values)s::jsonb,
                            %(config)s::jsonb, %(warnings)s::jsonb, %(data_quality_flags)s::jsonb
                        )
                        """,
                        {
                            "run_id": actual_run_id,
                            "created_at": actual_created_at,
                            "start_date": form.start_date,
                            "end_date": form.end_date,
                            "strategy_preset": form.strategy_preset.value,
                            "market_timing_overlay": form.market_timing_overlay.value,
                            "safe_asset_summary": form.safe_asset_summary(),
                            "initial_capital": form.initial_capital,
                            "top_n": form.top_n,
                            "transaction_cost_preset": form.transaction_cost_preset.value,
                            "final_gross_equity": final_point.gross_equity if final_point else None,
                            "final_net_equity": final_point.net_equity if final_point else None,
                            "final_benchmark_equity": final_point.benchmark_equity if final_point else None,
                            "gross_total_return": metrics.get("gross_total_return"),
                            "net_total_return": metrics.get("net_total_return"),
                            "gross_cagr": metrics.get("gross_cagr"),
                            "net_cagr": metrics.get("net_cagr"),
                            "max_drawdown_net": metrics.get("max_drawdown_net"),
                            "sharpe": metrics.get("sharpe"),
                            "trade_count": metrics.get("trade_count", 0),
                            "win_rate": metrics.get("win_rate"),
                            "expected_value": metrics.get("expected_value"),
                            "turnover": metrics.get("turnover"),
                            "total_fees": metrics.get("total_fees"),
                            "average_holding_period": metrics.get("average_holding_period"),
                            "metrics": Jsonb(_json_ready(metrics)),
                            "form_values": Jsonb(_json_ready(context.form_values)),
                            "config": Jsonb(_json_ready(config)),
                            "warnings": Jsonb(_json_ready(warnings)),
                            "data_quality_flags": Jsonb(_json_ready(simulation.data_quality_flags)),
                        },
                    )
                    for point in simulation.equity_curve:
                        cur.execute(
                            """
                            insert into mart.backtest_equity_curve (
                                run_id, equity_date, gross_equity, net_equity, benchmark_equity, details
                            ) values (
                                %(run_id)s, %(equity_date)s, %(gross_equity)s, %(net_equity)s, %(benchmark_equity)s,
                                %(details)s::jsonb
                            )
                            """,
                            {
                                "run_id": actual_run_id,
                                "equity_date": point.date,
                                "gross_equity": point.gross_equity,
                                "net_equity": point.net_equity,
                                "benchmark_equity": point.benchmark_equity,
                                "details": Jsonb({}),
                            },
                        )
                    for row in simulation.summary_rows:
                        cur.execute(
                            """
                            insert into mart.backtest_rebalance_summary (
                                run_id, signal_date, execution_date, selected_count, sold_count, buy_notional,
                                sell_notional, fees, turnover, notes, details
                            ) values (
                                %(run_id)s, %(signal_date)s, %(execution_date)s, %(selected_count)s, %(sold_count)s,
                                %(buy_notional)s, %(sell_notional)s, %(fees)s, %(turnover)s, %(notes)s,
                                %(details)s::jsonb
                            )
                            """,
                            {
                                "run_id": actual_run_id,
                                "signal_date": row.signal_date,
                                "execution_date": row.execution_date,
                                "selected_count": row.selected_count,
                                "sold_count": row.sold_count,
                                "buy_notional": row.buy_notional,
                                "sell_notional": row.sell_notional,
                                "fees": row.fees,
                                "turnover": row.turnover,
                                "notes": row.notes,
                                "details": Jsonb({}),
                            },
                        )
                    for row in simulation.fill_rows:
                        cur.execute(
                            """
                            insert into mart.backtest_fill_log (
                                run_id, execution_date, signal_date, symbol, action, shares, execution_price,
                                fees, net_cash_flow, realized_pnl, holding_days, details
                            ) values (
                                %(run_id)s, %(execution_date)s, %(signal_date)s, %(symbol)s, %(action)s,
                                %(shares)s, %(execution_price)s, %(fees)s, %(net_cash_flow)s, %(realized_pnl)s,
                                %(holding_days)s, %(details)s::jsonb
                            )
                            """,
                            {
                                "run_id": actual_run_id,
                                "execution_date": row.execution_date,
                                "signal_date": row.signal_date,
                                "symbol": row.symbol,
                                "action": row.action,
                                "shares": row.shares,
                                "execution_price": row.execution_price,
                                "fees": row.fees,
                                "net_cash_flow": row.net_cash_flow,
                                "realized_pnl": row.realized_pnl,
                                "holding_days": row.holding_days,
                                "details": Jsonb({}),
                            },
                        )
        return {
            "run_id": actual_run_id,
            "created_at": actual_created_at,
            "equity_points_saved": len(simulation.equity_curve),
            "rebalance_rows_saved": len(simulation.summary_rows),
            "fill_rows_saved": len(simulation.fill_rows),
            "summary_saved": 1,
        }

    def list_recent_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        self.ensure_backtest_result_tables()
        with postgres_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                select run_id, created_at, start_date, end_date, strategy_preset, market_timing_overlay,
                       safe_asset_summary, initial_capital, top_n, transaction_cost_preset,
                       net_total_return, max_drawdown_net, sharpe, trade_count, total_fees
                from mart.backtest_run_summary
                order by created_at desc
                limit %(limit)s
                """,
                {"limit": limit},
            )
            return [dict(row) for row in cur.fetchall()]

    def fetch_saved_run(self, run_id: str) -> dict[str, Any] | None:
        self.ensure_backtest_result_tables()
        with postgres_connection() as conn, conn.cursor() as cur:
            cur.execute(
                "select * from mart.backtest_run_summary where run_id = %(run_id)s",
                {"run_id": run_id},
            )
            summary = cur.fetchone()
            if summary is None:
                return None
            cur.execute(
                """
                select *
                from mart.backtest_equity_curve
                where run_id = %(run_id)s
                order by equity_date asc, id asc
                """,
                {"run_id": run_id},
            )
            equity_curve = [dict(row) for row in cur.fetchall()]
            cur.execute(
                """
                select *
                from mart.backtest_rebalance_summary
                where run_id = %(run_id)s
                order by execution_date asc, id asc
                """,
                {"run_id": run_id},
            )
            rebalance_rows = [dict(row) for row in cur.fetchall()]
            cur.execute(
                """
                select *
                from mart.backtest_fill_log
                where run_id = %(run_id)s
                order by execution_date asc, id asc
                """,
                {"run_id": run_id},
            )
            fill_rows = [dict(row) for row in cur.fetchall()]
            return {
                "summary": dict(summary),
                "equity_curve": equity_curve,
                "rebalance_rows": rebalance_rows,
                "fill_rows": fill_rows,
            }

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
            else tuple(f"mart.{preset.mart_table}" for preset in STRATEGY_PRESETS.values())
        )
        return (
            "stg.stg_daily_prices",
            "stg.stg_benchmark_series",
            *mart_relations,
        )

    def relation_probe_query(self, relation_name: str) -> str:
        return f"select 1 from {relation_name} limit 1"

    def required_support_symbols(self) -> tuple[str, ...]:
        return get_settings().support_market_symbols

    def support_symbol_probe_query(self) -> str:
        return """
            select symbol
            from stg.stg_daily_prices
            where symbol = any(%(symbols)s::text[])
              and coalesce(adjusted_close, close) is not null
            group by symbol
            order by symbol
        """

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
                support_symbols = self.required_support_symbols()
                cur.execute(self.support_symbol_probe_query(), {"symbols": list(support_symbols)})
                available_symbols = {row["symbol"] for row in cur.fetchall()}
                missing_symbols = [symbol for symbol in support_symbols if symbol not in available_symbols]
                if missing_symbols:
                    return ReadinessStatus(
                        ok=False,
                        code="missing_support_symbol_data",
                        detail=f"지원 심볼 가격 이력이 없습니다: {', '.join(missing_symbols)}",
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

    def fetch_spy_benchmark_values(self, start_date: date, end_date: date) -> list[BenchmarkValueRow]:
        with postgres_connection() as conn, conn.cursor() as cur:
            cur.execute(self.benchmark_value_query(), {"start_date": start_date, "end_date": end_date})
            return [
                BenchmarkValueRow(
                    observation_date=row["observation_date"],
                    value=row["value"],
                )
                for row in cur.fetchall()
            ]

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
