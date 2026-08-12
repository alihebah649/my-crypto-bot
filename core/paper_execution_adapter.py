"""
Paper Execution Adapter
=======================

Safe execution adapter for paper trading.

This adapter NEVER sends orders to Binance or any live broker. It simulates
order execution against a supplied market price and maintains a virtual cash
balance. It supports the project's SCALPING / SWING / SCALPING_SWING trade
modes through metadata; execution itself remains strategy-agnostic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from core.execution_models import (
    ExecutionResult,
    ExecutionSource,
    OrderFees,
    OrderRequest,
    OrderSide,
    OrderStatus,
)
from core.models import TradeType


@dataclass(slots=True)
class PaperBalance:
    cash: float
    reserved: float = 0.0
    assets: dict[str, float] = field(default_factory=dict)


class PaperExecutionAdapter:
    """Deterministic, exchange-free execution adapter for paper trading."""

    def __init__(self, initial_cash: float = 1000.0, fee_rate: float = 0.001) -> None:
        if initial_cash < 0:
            raise ValueError("initial_cash must be non-negative")
        if fee_rate < 0:
            raise ValueError("fee_rate must be non-negative")

        self.fee_rate = float(fee_rate)
        self.balance = PaperBalance(cash=float(initial_cash))
        self.orders: dict[str, ExecutionResult] = {}
        self.market_prices: dict[str, float] = {}

    def set_market_price(self, symbol: str, price: float) -> None:
        price = float(price)
        if price <= 0:
            raise ValueError("market price must be positive")
        self.market_prices[symbol.upper()] = price

    def get_market_price(self, symbol: str) -> float:
        try:
            return self.market_prices[symbol.upper()]
        except KeyError as exc:
            raise ValueError(f"No paper market price for {symbol}") from exc

    def execute(
        self,
        request: OrderRequest,
        *,
        market_price: Optional[float] = None,
        trade_type: TradeType = TradeType.SCALPING_SWING,
    ) -> ExecutionResult:
        symbol = request.symbol.upper()
        price = float(market_price) if market_price is not None else self.get_market_price(symbol)
        quantity = float(request.requested_quantity)

        if quantity <= 0:
            return self._rejected(request, "INVALID_QUANTITY")
        if price <= 0:
            return self._rejected(request, "INVALID_PRICE")

        gross = price * quantity
        fee = gross * self.fee_rate

        if request.side == OrderSide.BUY:
            total_cost = gross + fee
            if total_cost > self.balance.cash + 1e-12:
                return self._rejected(request, "INSUFFICIENT_BALANCE")
            self.balance.cash -= total_cost
            self.balance.assets[symbol] = self.balance.assets.get(symbol, 0.0) + quantity
        elif request.side == OrderSide.SELL:
            held = self.balance.assets.get(symbol, 0.0)
            if quantity > held + 1e-12:
                return self._rejected(request, "INSUFFICIENT_BALANCE")
            self.balance.assets[symbol] = max(0.0, held - quantity)
            self.balance.cash += gross - fee
        else:
            return self._rejected(request, "UNKNOWN")

        now = datetime.now(timezone.utc)
        result = ExecutionResult(
            request_id=request.request_id,
            client_order_id=request.client_order_id,
            exchange_order_id=f"PAPER-{uuid4().hex[:16]}",
            symbol=symbol,
            side=request.side,
            order_type=request.order_type,
            status=OrderStatus.FILLED,
            requested_price=price,
            requested_quantity=quantity,
            executed_price=price,
            executed_quantity=quantity,
            remaining_quantity=0.0,
            average_price=price,
            fees=OrderFees(total=fee),
            message=f"Paper execution: {trade_type.value}",
            created_at=now,
            submitted_at=now,
            completed_at=now,
            exchange="PAPER",
            raw_response={
                "source": ExecutionSource.PAPER.value,
                "trade_type": trade_type.value,
            },
        )
        self.orders[request.client_order_id] = result
        return result

    def _rejected(self, request: OrderRequest, reason: str) -> ExecutionResult:
        now = datetime.now(timezone.utc)
        result = ExecutionResult(
            request_id=request.request_id,
            client_order_id=request.client_order_id,
            symbol=request.symbol.upper(),
            side=request.side,
            order_type=request.order_type,
            status=OrderStatus.REJECTED,
            requested_price=request.requested_price,
            requested_quantity=request.requested_quantity,
            reject_reason=reason,
            message=f"Paper order rejected: {reason}",
            created_at=now,
            completed_at=now,
            exchange="PAPER",
            raw_response={"source": ExecutionSource.PAPER.value},
        )
        self.orders[request.client_order_id] = result
        return result

    def snapshot(self) -> dict[str, Any]:
        return {
            "source": ExecutionSource.PAPER.value,
            "cash": self.balance.cash,
            "reserved": self.balance.reserved,
            "assets": dict(self.balance.assets),
            "orders": len(self.orders),
            "fee_rate": self.fee_rate,
        }
