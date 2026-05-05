"""Alpaca Trading API 클라이언트 래퍼.

Paper trading 계좌 조회, 포지션 조회, 주문 내역 조회,
일괄 주문 제출을 담당합니다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, OrderStatus, QueryOrderStatus, TimeInForce
from alpaca.trading.requests import GetOrdersRequest, MarketOrderRequest

if TYPE_CHECKING:
    from quant_data_platform.config import Settings


# ---------------------------------------------------------------------------
# 데이터 전송 타입 (서비스/라우트가 사용하는 순수 dict 포맷)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AccountSummary:
    portfolio_value: Decimal
    cash: Decimal
    buying_power: Decimal
    equity: Decimal
    long_market_value: Decimal
    unrealized_pl: Decimal
    unrealized_plpc: Decimal  # 0.05 = 5%
    daytrade_count: int
    currency: str = "USD"


@dataclass(frozen=True)
class PositionRow:
    symbol: str
    qty: Decimal
    avg_entry_price: Decimal
    current_price: Decimal
    market_value: Decimal
    unrealized_pl: Decimal
    unrealized_plpc: Decimal  # 0.05 = 5%
    side: str  # "long" | "short"


@dataclass
class OrderResult:
    symbol: str
    order_id: str | None
    status: str  # "submitted" | "error"
    error: str | None = None
    side: str = ""
    qty: Decimal | None = None
    notional: Decimal | None = None


@dataclass(frozen=True)
class OrderHistoryRow:
    order_id: str
    symbol: str
    side: str
    qty: Decimal | None
    notional: Decimal | None
    filled_qty: Decimal | None
    filled_avg_price: Decimal | None
    status: str
    submitted_at: str
    filled_at: str | None
    time_in_force: str


@dataclass
class BatchOrderRequest:
    """일괄 주문 요청의 개별 항목."""
    symbol: str
    side: str          # "buy" | "sell"
    order_type: str    # "qty" | "notional"
    qty: Decimal | None = None
    notional: Decimal | None = None
    time_in_force: str = "day"


# ---------------------------------------------------------------------------
# 클라이언트
# ---------------------------------------------------------------------------


class AlpacaClient:
    """Alpaca TradingClient 래퍼.

    - SDK의 Pydantic 모델을 내부 dataclass로 변환하여 서비스 레이어를 SDK에서 분리합니다.
    - 키 미설정 시 ``ConfigurationError``를 발생시켜 상위에서 처리합니다.
    """

    def __init__(self, settings: "Settings") -> None:
        if not settings.alpaca_api_key or not settings.alpaca_secret_key:
            raise ConfigurationError("ALPACA_API_KEY 와 ALPACA_SECRET_KEY 환경변수가 설정되지 않았습니다.")
        self._client = TradingClient(
            settings.alpaca_api_key,
            settings.alpaca_secret_key,
            paper=settings.alpaca_paper,
        )

    # ------------------------------------------------------------------
    # 계좌 정보
    # ------------------------------------------------------------------

    def get_account(self) -> AccountSummary:
        a = self._client.get_account()
        return AccountSummary(
            portfolio_value=_dec(a.portfolio_value),
            cash=_dec(a.cash),
            buying_power=_dec(a.buying_power),
            equity=_dec(a.equity),
            long_market_value=_dec(a.long_market_value),
            unrealized_pl=getattr(a, "unrealized_pl", None) or Decimal("0"),
            unrealized_plpc=getattr(a, "unrealized_plpc", None) or Decimal("0"),
            daytrade_count=int(a.daytrade_count or 0),
            currency=str(a.currency or "USD"),
        )

    # ------------------------------------------------------------------
    # 포지션
    # ------------------------------------------------------------------

    def get_positions(self) -> list[PositionRow]:
        positions = self._client.get_all_positions()
        rows: list[PositionRow] = []
        for p in positions:
            rows.append(
                PositionRow(
                    symbol=str(p.symbol),
                    qty=_dec(p.qty),
                    avg_entry_price=_dec(p.avg_entry_price),
                    current_price=_dec(p.current_price),
                    market_value=_dec(p.market_value),
                    unrealized_pl=_dec(p.unrealized_pl),
                    unrealized_plpc=_dec(p.unrealized_plpc),
                    side=str(p.side.value if hasattr(p.side, "value") else p.side),
                )
            )
        rows.sort(key=lambda r: abs(r.market_value), reverse=True)
        return rows

    # ------------------------------------------------------------------
    # 주문 내역
    # ------------------------------------------------------------------

    def get_orders(self, limit: int = 50) -> list[OrderHistoryRow]:
        req = GetOrdersRequest(limit=limit, status=QueryOrderStatus.ALL)  # type: ignore[arg-type]
        orders = self._client.get_orders(filter=req)
        rows: list[OrderHistoryRow] = []
        for o in orders:
            rows.append(
                OrderHistoryRow(
                    order_id=str(o.id),
                    symbol=str(o.symbol),
                    side=str(o.side.value if hasattr(o.side, "value") else o.side),
                    qty=_dec(o.qty),
                    notional=_dec(o.notional),
                    filled_qty=_dec(o.filled_qty),
                    filled_avg_price=_dec(o.filled_avg_price),
                    status=str(o.status.value if hasattr(o.status, "value") else o.status),
                    submitted_at=_fmt_dt(o.submitted_at),
                    filled_at=_fmt_dt(o.filled_at),
                    time_in_force=str(o.time_in_force.value if hasattr(o.time_in_force, "value") else o.time_in_force),
                )
            )
        return rows

    # ------------------------------------------------------------------
    # 일괄 주문
    # ------------------------------------------------------------------

    def submit_batch_orders(self, requests: list[BatchOrderRequest]) -> list[OrderResult]:
        """requests를 순서대로 처리하여 각 결과를 반환합니다.

        실패한 항목이 있어도 계속 처리합니다 (개별 에러 기록).
        """
        results: list[OrderResult] = []
        for req in requests:
            result = self._submit_single(req)
            results.append(result)
        return results

    def _submit_single(self, req: BatchOrderRequest) -> OrderResult:
        try:
            side = OrderSide.BUY if req.side.lower() == "buy" else OrderSide.SELL
            tif = TimeInForce.DAY if req.time_in_force.lower() == "day" else TimeInForce.GTC

            if req.order_type == "notional":
                order_data = MarketOrderRequest(
                    symbol=req.symbol.upper(),
                    notional=float(req.notional),  # type: ignore[arg-type]
                    side=side,
                    time_in_force=TimeInForce.DAY,  # notional은 DAY만 지원
                )
            else:
                order_data = MarketOrderRequest(
                    symbol=req.symbol.upper(),
                    qty=float(req.qty),  # type: ignore[arg-type]
                    side=side,
                    time_in_force=tif,
                )

            order = self._client.submit_order(order_data=order_data)
            return OrderResult(
                symbol=req.symbol.upper(),
                order_id=str(order.id),
                status="submitted",
                side=req.side,
                qty=req.qty,
                notional=req.notional,
            )
        except Exception as exc:  # noqa: BLE001
            return OrderResult(
                symbol=req.symbol.upper(),
                order_id=None,
                status="error",
                error=str(exc),
                side=req.side,
                qty=req.qty,
                notional=req.notional,
            )


# ---------------------------------------------------------------------------
# 예외
# ---------------------------------------------------------------------------


class ConfigurationError(RuntimeError):
    """Alpaca 키 미설정 등 구성 오류."""


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------


def _dec(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    try:
        return Decimal(str(value))
    except Exception:  # noqa: BLE001
        return Decimal("0")


def _fmt_dt(dt: Any) -> str | None:
    if dt is None:
        return None
    try:
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:  # noqa: BLE001
        return str(dt)
