from __future__ import annotations

import csv
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from quant_data_platform.web.schemas import BacktestFormInput, BacktestPageContext
from quant_data_platform.web.services.engine import SimulationResult


DEFAULT_BACKTEST_RESULT_DIR = Path(__file__).resolve().parents[4] / "backtest_result"


def _stringify(value: Any) -> str:
    return "" if value is None else str(value)


class BacktestResultWriter:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir

    def write(
        self,
        *,
        form: BacktestFormInput,
        context: BacktestPageContext,
        simulation: SimulationResult,
        saved_at: datetime | None = None,
    ) -> Path:
        actual_saved_at = saved_at or datetime.now()
        target_dir = self._create_timestamp_dir(actual_saved_at)
        try:
            (target_dir / "backtest_input_summary.md").write_text(
                self._render_markdown(form=form, context=context, saved_at=actual_saved_at),
                encoding="utf-8",
            )
            self._write_rebalance_csv(target_dir / "rebalance_summary.csv", simulation)
            self._write_fill_csv(target_dir / "fill_log.csv", simulation)
        except OSError:
            shutil.rmtree(target_dir, ignore_errors=True)
            raise
        return target_dir

    def _create_timestamp_dir(self, base_time: datetime) -> Path:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        for offset in range(0, 300):
            candidate_time = base_time + timedelta(seconds=offset)
            candidate_dir = self.base_dir / candidate_time.strftime("%Y%m%d_%H%M%S")
            try:
                candidate_dir.mkdir(parents=False, exist_ok=False)
            except FileExistsError:
                continue
            return candidate_dir
        raise OSError("결과 저장용 디렉터리를 만들 수 없습니다.")

    def _render_markdown(
        self,
        *,
        form: BacktestFormInput,
        context: BacktestPageContext,
        saved_at: datetime,
    ) -> str:
        lines = [
            "# 백테스트 입력 + 핵심 성과 요약",
            "",
            f"- 저장 시각: {saved_at.isoformat(timespec='seconds')}",
            "",
            "## 입력값 요약",
            "",
            "| 항목 | 값 |",
            "| --- | --- |",
            f"| 전략 프리셋 | {context.selected_preset_detail.label if context.selected_preset_detail else form.strategy_preset.value} |",
            f"| 마켓타이밍 오버레이 | {context.selected_overlay_detail.label if context.selected_overlay_detail else form.market_timing_overlay.value} |",
            f"| 안전자산 | {context.selected_safe_asset_detail.label if context.selected_safe_asset_detail else form.safe_asset_symbol.value} |",
            f"| 시작일 | {form.start_date.isoformat()} |",
            f"| 종료일 | {form.end_date.isoformat()} |",
            f"| 초기 자본 | {form.initial_capital} |",
            f"| 보유 종목 수 (Top-N) | {form.top_n} |",
            f"| 거래비용 프리셋 | {context.selected_cost_detail.label if context.selected_cost_detail else form.transaction_cost_preset.value} |",
            "",
            "## 핵심 성과 요약",
            "",
            "| 지표 | 값 | 설명 |",
            "| --- | --- | --- |",
        ]
        lines.extend(
            f"| {metric.label} | {metric.value} | {metric.tooltip or ''} |"
            for metric in context.summary_metrics
        )
        if context.warnings:
            lines.extend(["", "## 경고 / 해석 메모", ""])
            lines.extend(f"- **{warning.title}**: {warning.body}" for warning in context.warnings)
        if context.data_quality_flags:
            lines.extend(["", "## 데이터 품질 메모", ""])
            lines.extend(f"- {flag}" for flag in context.data_quality_flags)
        return "\n".join(lines) + "\n"

    def _write_rebalance_csv(self, path: Path, simulation: SimulationResult) -> None:
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                [
                    "signal_date",
                    "execution_date",
                    "selected_count",
                    "sold_count",
                    "buy_notional",
                    "sell_notional",
                    "fees",
                    "turnover",
                    "notes",
                ]
            )
            for row in simulation.summary_rows:
                writer.writerow(
                    [
                        row.signal_date.isoformat(),
                        row.execution_date.isoformat(),
                        row.selected_count,
                        row.sold_count,
                        _stringify(row.buy_notional),
                        _stringify(row.sell_notional),
                        _stringify(row.fees),
                        _stringify(row.turnover),
                        _stringify(row.notes),
                    ]
                )

    def _write_fill_csv(self, path: Path, simulation: SimulationResult) -> None:
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                [
                    "execution_date",
                    "signal_date",
                    "symbol",
                    "action",
                    "shares",
                    "execution_price",
                    "fees",
                    "net_cash_flow",
                    "realized_pnl",
                    "holding_days",
                ]
            )
            for row in simulation.fill_rows:
                writer.writerow(
                    [
                        row.execution_date.isoformat(),
                        row.signal_date.isoformat(),
                        row.symbol,
                        row.action,
                        _stringify(row.shares),
                        _stringify(row.execution_price),
                        _stringify(row.fees),
                        _stringify(row.net_cash_flow),
                        _stringify(row.realized_pnl),
                        _stringify(row.holding_days),
                    ]
                )
