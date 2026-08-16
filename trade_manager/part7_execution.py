"""Trade Manager Part 7 - normalized execution contract layer.

Source basis: ``trade manager parts 1-7.docx`` sections 7.1-7.2.

The original document contains broker-specific skeletons and a second execution
model. This file preserves those responsibilities as adapters around the
repository's canonical ``integration_contracts`` and ``core_execution_gateway``.
It never contains Binance/REST calls and never changes Position state.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, auto
import logging
import time
import uuid
from typing import Any, Optional

from .integration_contracts import (
    ExecutionGateway,
    ExecutionOutcome,
    ExecutionOutcomeRecord,
    ExecutionRequest as GatewayRequest,
    ExecutionSide,
)

logger = logging.getLogger("TradeManager.Part7Execution")


class OrderSide(Enum):
    BUY = auto()
    SELL = auto()


class OrderType(Enum):
    MARKET = auto()
    LIMIT = auto()
    STOP = auto()
    STOP_LIMIT = auto()


class OrderStatus(Enum):
    CREATED = auto()
    VALIDATED = auto()
    SUBMITTED = auto()
    ACCEPTED = auto()
    FILLED = auto()
    PARTIALLY_FILLED = auto()
    CANCELLED = auto()
    REJECTED = auto()
    FAILED = auto()


@dataclass(slots=True)
class ExecutionOrder:
    order_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: float
    price: Optional[float] = None
    stop_price: Optional[float] = None
    client_order_id: Optional[str] = None
    status: OrderStatus = OrderStatus.CREATED
    exchange_order_id: Optional[str] = None
    filled_quantity: float = 0.0
    average_price: float = 0.0
    reject_reason: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


class ExecutionResultStatus(Enum):
    SUCCESS = auto()
    PARTIAL_FILL = auto()
    REJECTED = auto()
    FAILED = auto()
    TIMEOUT = auto()
    CANCELLED = auto()


@dataclass(slots=True)
class ExecutionResult:
    success: bool
    status: ExecutionResultStatus
    symbol: str
    side: str
    requested_quantity: float
    executed_quantity: float
    average_price: float
    exchange_order_id: Optional[str]
    client_order_id: Optional[str]
    commission: float = 0.0
    commission_asset: str = ""
    message: str = ""
    timestamp: float = field(default_factory=time.time)


@dataclass(slots=True)
class ExecutionError:
    code: str
    message: str
    recoverable: bool = False
    retry_after: float = 0.0
    timestamp: float = field(default_factory=time.time)


@dataclass(slots=True)
class ExecutionResponse:
    result: Optional[ExecutionResult] = None
    error: Optional[ExecutionError] = None
    latency_ms: float = 0.0
    raw_response: Optional[dict[str, Any]] = None

    @property
    def ok(self) -> bool:
        return self.result is not None and self.result.success


class ExecutionBroker(ABC):
    """Official Part-7 broker interface; implementations live outside TM."""

    @abstractmethod
    def submit_order(self, order: ExecutionOrder) -> ExecutionResponse:
        raise NotImplementedError

    @abstractmethod
    def cancel_order(self, *, symbol: str, order_id: Optional[str] = None,
                     client_order_id: Optional[str] = None) -> ExecutionResponse:
        raise NotImplementedError

    @abstractmethod
    def get_order(self, *, symbol: str, order_id: Optional[str] = None,
                  client_order_id: Optional[str] = None) -> ExecutionResponse:
        raise NotImplementedError

    @abstractmethod
    def modify_stop_loss(self, *, symbol: str, position_id: str,
                         stop_price: float) -> ExecutionResponse:
        raise NotImplementedError

    @abstractmethod
    def close_position(self, *, symbol: str, quantity: float) -> ExecutionResponse:
        raise NotImplementedError

    @abstractmethod
    def ping(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def server_time(self) -> float:
        raise NotImplementedError


class ExecutionRequestBuilder:
    """Builds normalized orders; it does not validate balances or execute."""

    def __init__(self, client_prefix: str = "BOT") -> None:
        self.client_prefix = client_prefix

    def build_market_order(self, *, symbol: str, side: OrderSide,
                           quantity: float) -> ExecutionOrder:
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        return ExecutionOrder(
            order_id=f"ORD-{uuid.uuid4().hex[:16]}",
            symbol=symbol.upper(),
            side=side,
            order_type=OrderType.MARKET,
            quantity=quantity,
            client_order_id=f"{self.client_prefix}-{uuid.uuid4().hex[:16]}",
        )

    def build_limit_order(self, *, symbol: str, side: OrderSide,
                          quantity: float, price: float) -> ExecutionOrder:
        if quantity <= 0 or price <= 0:
            raise ValueError("quantity and price must be positive")
        return ExecutionOrder(
            order_id=f"ORD-{uuid.uuid4().hex[:16]}", symbol=symbol.upper(), side=side,
            order_type=OrderType.LIMIT, quantity=quantity, price=price,
            client_order_id=f"{self.client_prefix}-{uuid.uuid4().hex[:16]}",
        )


class ExecutionErrorHandler:
    """Classifies execution exceptions without hiding them."""

    def __init__(self, retry_limit: int = 3, retry_delay: float = 0.5) -> None:
        self.retry_limit = max(0, retry_limit)
        self.retry_delay = max(0.0, retry_delay)

    def classify(self, exception: Exception) -> str:
        text = str(exception).lower()
        if "timeout" in text or "timed out" in text:
            return "TIMEOUT"
        if any(token in text for token in ("network", "connection", "temporarily", "429")):
            return "NETWORK"
        if any(token in text for token in ("insufficient", "balance", "min notional")):
            return "REJECTED"
        return "UNKNOWN"

    def should_retry(self, exception: Exception, current_attempt: int) -> bool:
        return self.classify(exception) in {"TIMEOUT", "NETWORK"} and current_attempt < self.retry_limit

    def wait_before_retry(self, attempt: int) -> None:
        time.sleep(self.retry_delay * max(1, attempt))

    def build_execution_error(self, exception: Exception) -> ExecutionError:
        code = self.classify(exception)
        return ExecutionError(code, str(exception), code in {"TIMEOUT", "NETWORK"}, self.retry_delay)

    def is_fatal(self, exception: Exception) -> bool:
        return not self.build_execution_error(exception).recoverable

    def log(self, exception: Exception) -> None:
        logger.exception("Execution error: %s", exception)

    def handle(self, exception: Exception) -> ExecutionResponse:
        self.log(exception)
        return ExecutionResponse(error=self.build_execution_error(exception))


class BrokerUtilities:
    """Non-trading helpers from Part 7.1F.6."""

    @staticmethod
    def now() -> float:
        return time.time()

    @staticmethod
    def start_timer() -> float:
        return time.perf_counter()

    @staticmethod
    def stop_timer(start_time: float) -> float:
        return max(0.0, (time.perf_counter() - start_time) * 1000.0)

    @staticmethod
    def safe_float(value: Any, default: float = 0.0) -> float:
        try:
            result = float(value)
            return result if result == result else default
        except (TypeError, ValueError):
            return default

    @staticmethod
    def safe_string(value: Any, default: str = "") -> str:
        return default if value is None else str(value)

    @staticmethod
    def safe_get(data: dict, key: str, default: Any = None) -> Any:
        try:
            return data.get(key, default)
        except AttributeError:
            return default

    @staticmethod
    def normalize_symbol(symbol: str) -> str:
        if not isinstance(symbol, str) or not symbol.strip():
            raise ValueError("symbol must be a non-empty string")
        return symbol.strip().upper()

    @staticmethod
    def generate_client_order_id(symbol: str) -> str:
        return f"BOT-{BrokerUtilities.normalize_symbol(symbol)}-{uuid.uuid4().hex[:12]}"

    @staticmethod
    def validate_response(response: dict) -> bool:
        return isinstance(response, dict) and bool(response)

    @staticmethod
    def log_request(request: dict) -> None:
        logger.debug("Execution request: %s", request)

    @staticmethod
    def log_response(response: dict) -> None:
        logger.debug("Execution response: %s", response)

    @staticmethod
    def log_exception(exception: Exception) -> None:
        logger.exception("Execution exception: %s", exception)


class TradeManagerExecutionPipeline:
    """Part-7 pipeline over the canonical Trade Manager execution gateway."""

    def __init__(self, gateway: ExecutionGateway,
                 error_handler: Optional[ExecutionErrorHandler] = None) -> None:
        self.gateway = gateway
        self.error_handler = error_handler or ExecutionErrorHandler()

    def execute(self, order: ExecutionOrder) -> ExecutionResponse:
        start = time.perf_counter()
        try:
            request = GatewayRequest(
                symbol=order.symbol,
                side=ExecutionSide.BUY if order.side is OrderSide.BUY else ExecutionSide.SELL,
                quantity=order.quantity,
                order_type=order.order_type.name,
                price=order.price,
                stop_price=order.stop_price,
                client_order_id=order.client_order_id,
                metadata={"part7_order_id": order.order_id},
            )
            record = self.gateway.submit(request)
            return self._from_record(record, (time.perf_counter() - start) * 1000.0)
        except Exception as exc:
            response = self.error_handler.handle(exc)
            response.latency_ms = (time.perf_counter() - start) * 1000.0
            return response

    def close_spot(self, *, symbol: str, quantity: float,
                   client_order_id: Optional[str] = None) -> ExecutionResponse:
        start = time.perf_counter()
        try:
            record = self.gateway.close_spot(symbol=symbol, quantity=quantity,
                                             client_order_id=client_order_id)
            return self._from_record(record, (time.perf_counter() - start) * 1000.0)
        except Exception as exc:
            response = self.error_handler.handle(exc)
            response.latency_ms = (time.perf_counter() - start) * 1000.0
            return response

    @staticmethod
    def _from_record(record: ExecutionOutcomeRecord, latency_ms: float) -> ExecutionResponse:
        status_map = {
            ExecutionOutcome.SUCCESS: ExecutionResultStatus.SUCCESS,
            ExecutionOutcome.PARTIAL: ExecutionResultStatus.PARTIAL_FILL,
            ExecutionOutcome.REJECTED: ExecutionResultStatus.REJECTED,
            ExecutionOutcome.TIMEOUT: ExecutionResultStatus.TIMEOUT,
            ExecutionOutcome.CANCELLED: ExecutionResultStatus.CANCELLED,
            ExecutionOutcome.FAILED: ExecutionResultStatus.FAILED,
        }
        result = ExecutionResult(
            success=record.success,
            status=status_map[record.outcome],
            symbol=record.symbol,
            side=record.side.value,
            requested_quantity=record.requested_quantity,
            executed_quantity=record.executed_quantity,
            average_price=record.average_price,
            exchange_order_id=record.exchange_order_id,
            client_order_id=record.client_order_id,
            commission=record.commission,
            commission_asset=record.commission_asset,
            message=record.message,
        )
        return ExecutionResponse(result=result, latency_ms=latency_ms,
                                 raw_response=dict(record.metadata))


__all__ = [
    "OrderSide", "OrderType", "OrderStatus", "ExecutionOrder", "ExecutionResultStatus",
    "ExecutionResult", "ExecutionError", "ExecutionResponse", "ExecutionBroker",
    "ExecutionRequestBuilder", "ExecutionErrorHandler", "BrokerUtilities",
    "TradeManagerExecutionPipeline",
]
