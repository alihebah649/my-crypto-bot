"""Bridge the core execution engine into the Trade Manager contract.

This adapter is intentionally thin: Trade Manager owns the lifecycle contract,
while ``core.execution_adapter.ExecutionAdapter`` remains the only execution
implementation. It supports paper and live adapters without duplicating order
logic inside Trade Manager.
"""
from __future__ import annotations

from typing import Any
from uuid import uuid4

from core.execution_adapter import ExecutionAdapter
from core.execution_models import (
    ExecutionContext,
    ExecutionRequest as CoreExecutionRequest,
    ExecutionSource,
    OrderSide,
    OrderStatus,
    OrderType,
)

from .integration_contracts import (
    ExecutionGateway,
    ExecutionOutcome,
    ExecutionOutcomeRecord,
    ExecutionRequest,
    ExecutionSide,
)


class CoreExecutionGateway(ExecutionGateway):
    """Adapter from Trade Manager execution requests to the core adapter."""

    def __init__(self, adapter: ExecutionAdapter, *, source: ExecutionSource | None = None) -> None:
        self.adapter = adapter
        self.source = source or ExecutionSource.PAPER

    def submit(self, request: ExecutionRequest) -> ExecutionOutcomeRecord:
        if request.quantity <= 0:
            return self._failed(request, ExecutionOutcome.REJECTED, "quantity must be positive")

        try:
            core_request = CoreExecutionRequest(
                symbol=request.symbol.upper(),
                side=OrderSide(request.side.value),
                order_type=OrderType(request.order_type.upper()),
                price=request.price,
                stop_price=request.stop_price,
                quantity=request.quantity,
                client_order_id=request.client_order_id or f"TM-{uuid4().hex[:16]}",
                request_id=f"TM-REQ-{uuid4().hex[:16]}",
                context=ExecutionContext(
                    exchange_name=getattr(self.adapter, "exchange_name", ""),
                    source=self.source,
                    metadata=dict(request.metadata),
                ),
            )
            result = self.adapter.execute(core_request)
            return self._map_result(request, result)
        except Exception as exc:
            return self._failed(request, ExecutionOutcome.FAILED, str(exc))

    def cancel(
        self,
        *,
        symbol: str,
        exchange_order_id: str | None = None,
        client_order_id: str | None = None,
    ) -> ExecutionOutcomeRecord:
        order_id = exchange_order_id or client_order_id
        if not order_id:
            return ExecutionOutcomeRecord(
                success=False,
                outcome=ExecutionOutcome.REJECTED,
                symbol=symbol.upper(),
                side=ExecutionSide.SELL,
                requested_quantity=0.0,
                executed_quantity=0.0,
                average_price=0.0,
                message="cancel requires an exchange or client order id",
            )
        try:
            cancelled = self.adapter.cancel_order(symbol.upper(), order_id)
            return ExecutionOutcomeRecord(
                success=bool(cancelled),
                outcome=ExecutionOutcome.CANCELLED if cancelled else ExecutionOutcome.FAILED,
                symbol=symbol.upper(),
                side=ExecutionSide.SELL,
                requested_quantity=0.0,
                executed_quantity=0.0,
                average_price=0.0,
                exchange_order_id=exchange_order_id,
                client_order_id=client_order_id,
                message="order cancelled" if cancelled else "order could not be cancelled",
            )
        except Exception as exc:
            return ExecutionOutcomeRecord(
                success=False,
                outcome=ExecutionOutcome.FAILED,
                symbol=symbol.upper(),
                side=ExecutionSide.SELL,
                requested_quantity=0.0,
                executed_quantity=0.0,
                average_price=0.0,
                exchange_order_id=exchange_order_id,
                client_order_id=client_order_id,
                message=str(exc),
            )

    def close_spot(
        self,
        *,
        symbol: str,
        quantity: float,
        client_order_id: str | None = None,
    ) -> ExecutionOutcomeRecord:
        return self.submit(
            ExecutionRequest(
                symbol=symbol,
                side=ExecutionSide.SELL,
                quantity=quantity,
                order_type="MARKET",
                client_order_id=client_order_id,
                metadata={"trade_manager_action": "SPOT_CLOSE"},
            )
        )

    @staticmethod
    def _map_result(request: ExecutionRequest, result: Any) -> ExecutionOutcomeRecord:
        status = getattr(result, "status", None)
        status_value = getattr(status, "value", str(status))
        if status_value == OrderStatus.FILLED.value:
            outcome = ExecutionOutcome.SUCCESS
        elif status_value == OrderStatus.PARTIALLY_FILLED.value:
            outcome = ExecutionOutcome.PARTIAL
        elif status_value == OrderStatus.REJECTED.value:
            outcome = ExecutionOutcome.REJECTED
        elif status_value == OrderStatus.CANCELLED.value:
            outcome = ExecutionOutcome.CANCELLED
        else:
            outcome = ExecutionOutcome.FAILED

        fees = getattr(getattr(result, "fees", None), "total", 0.0)
        return ExecutionOutcomeRecord(
            success=outcome in (ExecutionOutcome.SUCCESS, ExecutionOutcome.PARTIAL),
            outcome=outcome,
            symbol=getattr(result, "symbol", request.symbol).upper(),
            side=request.side,
            requested_quantity=request.quantity,
            executed_quantity=float(getattr(result, "executed_quantity", 0.0)),
            average_price=float(getattr(result, "average_price", 0.0)),
            exchange_order_id=getattr(result, "exchange_order_id", None),
            client_order_id=getattr(result, "client_order_id", None),
            commission=float(fees),
            message=str(getattr(result, "message", "")),
            metadata={"core_status": status_value},
        )

    @staticmethod
    def _failed(request: ExecutionRequest, outcome: ExecutionOutcome, message: str) -> ExecutionOutcomeRecord:
        return ExecutionOutcomeRecord(
            success=False,
            outcome=outcome,
            symbol=request.symbol.upper(),
            side=request.side,
            requested_quantity=request.quantity,
            executed_quantity=0.0,
            average_price=0.0,
            client_order_id=request.client_order_id,
            message=message,
        )
