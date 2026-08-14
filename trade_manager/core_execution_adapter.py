"""Explicit bridge from core ExecutionAdapter to Trade Manager Part-7 broker API.

Integration boundary:
    Trade Manager Part 7 -> this adapter -> core.execution_adapter.ExecutionAdapter

The adapter translates models only. Strategy, risk, portfolio accounting and
position lifecycle remain outside this module.
"""
from __future__ import annotations

from typing import Any

from core.execution_adapter import ExecutionAdapter
from core.execution_models import (
    ExecutionContext,
    ExecutionRequest,
    OrderSide as CoreOrderSide,
    OrderType as CoreOrderType,
)

from .execution import ExecutionBroker, ExecutionOrder, ExecutionResult, OrderSide, OrderType


class CoreExecutionBrokerAdapter(ExecutionBroker):
    """Expose a core ExecutionAdapter through the Part-7 broker contract."""

    def __init__(self, adapter: ExecutionAdapter, *, strategy_name: str = "") -> None:
        self.adapter = adapter
        self.strategy_name = strategy_name

    def _request(self, order: ExecutionOrder) -> ExecutionRequest:
        side = CoreOrderSide.BUY if order.side is OrderSide.BUY else CoreOrderSide.SELL
        order_type = CoreOrderType.MARKET if order.order_type is OrderType.MARKET else CoreOrderType.LIMIT
        return ExecutionRequest(
            symbol=order.symbol.upper(),
            side=side,
            order_type=order_type,
            price=order.price,
            quantity=float(order.quantity),
            client_order_id=order.client_order_id,
            context=ExecutionContext(
                strategy_name=self.strategy_name,
                exchange_name=self.adapter.exchange_name,
                metadata={"trade_manager_client_order_id": order.client_order_id},
            ),
        )

    @staticmethod
    def _result(order: ExecutionOrder, result: Any) -> ExecutionResult:
        side = order.side.value
        fees = getattr(getattr(result, "fees", None), "total", 0.0)
        status = getattr(getattr(result, "status", None), "value", "")
        success = status == "FILLED" or bool(getattr(result, "executed_quantity", 0.0) > 0)
        return ExecutionResult(
            success=success,
            symbol=order.symbol.upper(),
            side=side,
            requested_quantity=order.quantity,
            executed_quantity=float(getattr(result, "executed_quantity", 0.0) or 0.0),
            average_price=float(getattr(result, "average_price", 0.0) or getattr(result, "executed_price", 0.0) or 0.0),
            commission=float(fees or 0.0),
            commission_asset="",
            exchange_order_id=getattr(result, "exchange_order_id", None),
            client_order_id=getattr(result, "client_order_id", None) or order.client_order_id,
            message=getattr(result, "message", "") or status,
            raw=getattr(result, "raw_response", None),
        )

    def submit_order(self, order: ExecutionOrder) -> ExecutionResult:
        request = self._request(order)
        result = self.adapter.execute(request)
        return self._result(order, result)

    def query_order(
        self,
        symbol: str,
        order_id: str | None = None,
        client_order_id: str | None = None,
    ) -> ExecutionResult:
        if not order_id:
            return ExecutionResult(False, symbol.upper(), "", 0.0, message="ORDER_ID_REQUIRED")
        raw = self.adapter.get_order(symbol.upper(), order_id)
        if not raw:
            return ExecutionResult(False, symbol.upper(), "", 0.0,
                                   exchange_order_id=order_id, message="ORDER_NOT_FOUND")
        side = str(raw.get("side", ""))
        try:
            tm_side = OrderSide(side)
        except ValueError:
            return ExecutionResult(False, symbol.upper(), side, 0.0,
                                   exchange_order_id=order_id, message="INVALID_BROKER_SIDE", raw=raw)
        order = ExecutionOrder(
            symbol=symbol.upper(),
            side=tm_side,
            quantity=float(raw.get("executedQty", 0.0) or 0.0),
            price=float(raw.get("price", 0.0) or 0.0) or None,
            client_order_id=client_order_id or str(raw.get("clientOrderId", "")),
        )
        return ExecutionResult(
            success=str(raw.get("status", "")) == "FILLED",
            symbol=order.symbol,
            side=order.side.value,
            requested_quantity=order.quantity,
            executed_quantity=order.quantity,
            average_price=float(raw.get("price", 0.0) or 0.0),
            exchange_order_id=str(raw.get("orderId", order_id)),
            client_order_id=order.client_order_id,
            message=str(raw.get("status", "")),
            raw=raw,
        )

    def cancel_order(
        self,
        symbol: str,
        order_id: str | None = None,
        client_order_id: str | None = None,
    ) -> ExecutionResult:
        if not order_id:
            return ExecutionResult(False, symbol.upper(), "", 0.0, message="ORDER_ID_REQUIRED")
        ok = self.adapter.cancel_order(symbol.upper(), order_id)
        return ExecutionResult(
            success=bool(ok),
            symbol=symbol.upper(),
            side="",
            requested_quantity=0.0,
            exchange_order_id=order_id,
            client_order_id=client_order_id,
            message="CANCELLED" if ok else "CANCEL_FAILED",
        )
