"""Alpaca Paper Trading 페이지 서비스.

AlpacaClient를 호출하여 템플릿에 넘길 컨텍스트를 생성합니다.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from quant_data_platform.clients.alpaca import (
    AccountSummary,
    AlpacaClient,
    BatchOrderRequest,
    ConfigurationError,
    OrderHistoryRow,
    OrderResult,
    PositionRow,
)
from quant_data_platform.config import Settings, get_settings


# ---------------------------------------------------------------------------
# 뷰 모델 (템플릿용 포맷팅 포함)
# ---------------------------------------------------------------------------

_CENT = Decimal("0.01")
_BP = Decimal("0.0001")


def _fmt_usd(v: Decimal) -> str:
    return f"${v.quantize(_CENT):,}"


def _fmt_pct(v: Decimal) -> str:
    pct = (v * 100).quantize(_CENT)
    sign = "+" if pct > 0 else ""
    return f"{sign}{pct}%"


def _pct_class(v: Decimal) -> str:
    if v > 0:
        return "positive"
    if v < 0:
        return "negative"
    return "neutral"


@dataclass
class PositionViewModel:
    symbol: str
    qty: str
    avg_entry_price: str
    current_price: str
    market_value: str
    unrealized_pl: str
    unrealized_plpc: str
    unrealized_plpc_class: str
    weight_pct: str
    side: str

    @staticmethod
    def from_row(row: PositionRow, total_market_value: Decimal) -> "PositionViewModel":
        weight = (row.market_value / total_market_value * 100).quantize(_CENT) if total_market_value else Decimal(0)
        return PositionViewModel(
            symbol=row.symbol,
            qty=str(row.qty.quantize(_CENT)),
            avg_entry_price=_fmt_usd(row.avg_entry_price),
            current_price=_fmt_usd(row.current_price),
            market_value=_fmt_usd(row.market_value),
            unrealized_pl=_fmt_usd(row.unrealized_pl),
            unrealized_plpc=_fmt_pct(row.unrealized_plpc),
            unrealized_plpc_class=_pct_class(row.unrealized_plpc),
            weight_pct=f"{weight}%",
            side=row.side,
        )


@dataclass
class OrderHistoryViewModel:
    order_id: str
    symbol: str
    side: str
    side_label: str
    qty: str
    notional: str
    filled_qty: str
    filled_avg_price: str
    status: str
    status_class: str
    submitted_at: str
    filled_at: str
    time_in_force: str

    @staticmethod
    def from_row(row: OrderHistoryRow) -> "OrderHistoryViewModel":
        _STATUS_CLASS = {
            "filled": "status-filled",
            "canceled": "status-canceled",
            "rejected": "status-rejected",
            "accepted": "status-pending",
            "new": "status-pending",
            "partially_filled": "status-pending",
        }
        return OrderHistoryViewModel(
            order_id=row.order_id[:8] + "…",
            symbol=row.symbol,
            side=row.side,
            side_label="매수" if row.side == "buy" else "매도",
            qty=str(row.qty.quantize(_CENT)) if row.qty else "-",
            notional=_fmt_usd(row.notional) if row.notional else "-",
            filled_qty=str(row.filled_qty.quantize(_CENT)) if row.filled_qty else "-",
            filled_avg_price=_fmt_usd(row.filled_avg_price) if row.filled_avg_price else "-",
            status=row.status,
            status_class=_STATUS_CLASS.get(row.status, "status-other"),
            submitted_at=row.submitted_at or "-",
            filled_at=row.filled_at or "-",
            time_in_force=row.time_in_force,
        )


@dataclass
class AccountViewModel:
    portfolio_value: str
    cash: str
    buying_power: str
    long_market_value: str
    unrealized_pl: str
    unrealized_plpc: str
    unrealized_plpc_class: str
    daytrade_count: int
    currency: str

    @staticmethod
    def from_summary(
        s: AccountSummary,
        total_unrealized_pl: Decimal | None = None,
        total_unrealized_plpc: Decimal | None = None,
    ) -> "AccountViewModel":
        pl = total_unrealized_pl if total_unrealized_pl is not None else s.unrealized_pl
        plpc = total_unrealized_plpc if total_unrealized_plpc is not None else s.unrealized_plpc
        return AccountViewModel(
            portfolio_value=_fmt_usd(s.portfolio_value),
            cash=_fmt_usd(s.cash),
            buying_power=_fmt_usd(s.buying_power),
            long_market_value=_fmt_usd(s.long_market_value),
            unrealized_pl=_fmt_usd(pl),
            unrealized_plpc=_fmt_pct(plpc),
            unrealized_plpc_class=_pct_class(plpc),
            daytrade_count=s.daytrade_count,
            currency=s.currency,
        )


@dataclass
class OrderResultViewModel:
    symbol: str
    order_id: str
    status: str
    status_class: str
    side: str
    qty: str
    notional: str
    error: str

    @staticmethod
    def from_result(r: OrderResult) -> "OrderResultViewModel":
        return OrderResultViewModel(
            symbol=r.symbol,
            order_id=r.order_id or "-",
            status=r.status,
            status_class="status-filled" if r.status == "submitted" else "status-rejected",
            side=r.side,
            qty=str(r.qty.quantize(_CENT)) if r.qty else "-",
            notional=_fmt_usd(r.notional) if r.notional else "-",
            error=r.error or "",
        )


# ---------------------------------------------------------------------------
# 서비스
# ---------------------------------------------------------------------------


class AlpacaPageService:
    """Alpaca 페이지의 모든 비즈니스 로직을 담당합니다."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._client: AlpacaClient | None = None
        self._init_error: str | None = None
        try:
            self._client = AlpacaClient(self._settings)
        except ConfigurationError as exc:
            self._init_error = str(exc)

    # ------------------------------------------------------------------
    # 페이지 컨텍스트
    # ------------------------------------------------------------------

    def get_page_context(self) -> dict[str, Any]:
        """GET /alpaca 에서 사용할 컨텍스트를 반환합니다."""
        base = {
            "page_title": "Alpaca Paper Trading",
            "active_tab": "alpaca",
            "state": "empty",
            "error_message": None,
            "account": None,
            "positions": [],
            "orders": [],
        }

        if self._init_error:
            base["state"] = "error"
            base["error_message"] = self._init_error
            return base

        try:
            account_raw = self._client.get_account()  # type: ignore[union-attr]
            positions_raw = self._client.get_positions()  # type: ignore[union-attr]
            orders_raw = self._client.get_orders(limit=50)  # type: ignore[union-attr]

            total_mv = sum((p.market_value for p in positions_raw), Decimal(0))
            
            # TradeAccount에 unrealized_pl이 없는 경우 포지션의 합계로 계산합니다.
            total_unrealized_pl = sum((p.unrealized_pl for p in positions_raw), Decimal(0))
            cost_basis = sum((p.qty * p.avg_entry_price for p in positions_raw), Decimal(0))
            total_unrealized_plpc = (total_unrealized_pl / cost_basis) if cost_basis > 0 else Decimal(0)

            base.update(
                {
                    "state": "ok",
                    "account": asdict(AccountViewModel.from_summary(
                        account_raw,
                        total_unrealized_pl=total_unrealized_pl,
                        total_unrealized_plpc=total_unrealized_plpc,
                    )),
                    "positions": [
                        asdict(PositionViewModel.from_row(p, total_mv)) for p in positions_raw
                    ],
                    "orders": [asdict(OrderHistoryViewModel.from_row(o)) for o in orders_raw],
                    "position_count": len(positions_raw),
                }
            )
        except Exception as exc:  # noqa: BLE001
            base["state"] = "error"
            base["error_message"] = f"Alpaca API 조회 실패: {exc}"

        return base

    # ------------------------------------------------------------------
    # 일괄 주문
    # ------------------------------------------------------------------

    def submit_orders(self, order_inputs: list[dict[str, Any]]) -> dict[str, Any]:
        """POST /alpaca/orders 에서 호출됩니다.

        order_inputs 형식::

            [
              {"symbol": "AAPL", "side": "buy", "order_type": "notional", "notional": "1000"},
              {"symbol": "MSFT", "side": "sell", "order_type": "qty", "qty": "5"},
              ...
            ]
        """
        if self._init_error:
            return {"ok": False, "error": self._init_error, "results": []}

        batch = _parse_batch_requests(order_inputs)
        if not batch:
            return {"ok": False, "error": "주문 항목이 없습니다.", "results": []}

        raw_results = self._client.submit_batch_orders(batch)  # type: ignore[union-attr]
        view_results = [asdict(OrderResultViewModel.from_result(r)) for r in raw_results]
        success_count = sum(1 for r in raw_results if r.status == "submitted")
        error_count = len(raw_results) - success_count
        return {
            "ok": error_count == 0,
            "error": None,
            "results": view_results,
            "summary": {
                "total": len(raw_results),
                "submitted": success_count,
                "errors": error_count,
            },
        }


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------


def _parse_batch_requests(inputs: list[dict[str, Any]]) -> list[BatchOrderRequest]:
    parsed: list[BatchOrderRequest] = []
    for item in inputs:
        symbol = str(item.get("symbol", "")).strip().upper()
        if not symbol:
            continue
        side = str(item.get("side", "buy")).lower()
        order_type = str(item.get("order_type", "notional")).lower()
        tif = str(item.get("time_in_force", "day")).lower()
        try:
            qty = Decimal(str(item["qty"])) if item.get("qty") else None
            notional = Decimal(str(item["notional"])) if item.get("notional") else None
        except Exception:  # noqa: BLE001
            continue
        if order_type == "qty" and not qty:
            continue
        if order_type == "notional" and not notional:
            continue
        parsed.append(
            BatchOrderRequest(
                symbol=symbol,
                side=side,
                order_type=order_type,
                qty=qty,
                notional=notional,
                time_in_force=tif,
            )
        )
    return parsed
