from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class ExecutionStatus(str, Enum):
    CREATED = "CREATED"
    SUBMITTED = "SUBMITTED"
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


@dataclass(slots=True)
class ExecutionOrder:
    symbol: str
    side: OrderSide
    quantity: float
    order_type: OrderType = OrderType.MARKET
    price: float | None = None
    client_order_id: str = field(default_factory=lambda: f"TM-{uuid.uuid4().hex[:20].upper()}")


@dataclass(slots=True)
class ExecutionResult:
    """Part-7 result consumed by Trade Manager and the Part-8 lifecycle."""

    success: bool
    symbol: str
    side: str
    requested_quantity: float
    executed_quantity: float = 0.0
    average_price: float = 0.0
    commission: float = 0.0
    commission_asset: str = ""
    exchange_order_id: str | None = None
    client_order_id: str | None = None
    message: str = ""
    raw: dict[str, Any] | None = None
    status: ExecutionStatus = ExecutionStatus.UNKNOWN
    remaining_quantity: float = 0.0

    @property
    def fully_filled(self) -> bool:
        return self.status is ExecutionStatus.FILLED and self.remaining_quantity <= 0.0


class ExecutionBroker(Protocol):
    def submit_order(self, order: ExecutionOrder) -> ExecutionResult: ...

    def query_order(self, symbol: str, order_id: str | None = None,
                    client_order_id: str | None = None) -> ExecutionResult: ...

    def cancel_order(self, symbol: str, order_id: str | None = None,
                     client_order_id: str | None = None) -> ExecutionResult: ...


class ExecutionPipeline:
    """Part 7 coordinator. Validation happens before the broker call."""

    def __init__(self, broker: ExecutionBroker, validator=None, audit_logger=None):
        self.broker = broker
        self.validator = validator
        self.audit_logger = audit_logger

    def execute(self, order: ExecutionOrder) -> ExecutionResult:
        if not order.symbol or order.quantity <= 0:
            return ExecutionResult(False, order.symbol, order.side.value, order.quantity,
                                   message="INVALID_ORDER", status=ExecutionStatus.REJECTED)
        if self.validator is not None:
            result = self.validator(order)
            if result is False:
                return ExecutionResult(False, order.symbol, order.side.value, order.quantity,
                                       message="VALIDATION_FAILED", status=ExecutionStatus.REJECTED)
        started = time.perf_counter()
        try:
            result = self.broker.submit_order(order)
        except Exception as exc:
            result = ExecutionResult(False, order.symbol, order.side.value, order.quantity,
                                     client_order_id=order.client_order_id, message=str(exc),
                                     status=ExecutionStatus.FAILED)
        if self.audit_logger is not None:
            self.audit_logger(result, (time.perf_counter() - started) * 1000.0)
        return result
