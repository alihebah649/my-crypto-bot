from __future__ import annotations

from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Any
from math import fsum

# ==========================================================
# Order Side
# ==========================================================

class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


# ==========================================================
# Order Type
# ==========================================================

class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP_MARKET = "STOP_MARKET"
    STOP_LIMIT = "STOP_LIMIT"


# ==========================================================
# Order Status
# ==========================================================

class OrderStatus(str, Enum):
    CREATED = "CREATED"
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"


# ==========================================================
# Time In Force
# ==========================================================

class TimeInForce(str, Enum):
    GTC = "GTC"
    IOC = "IOC"
    FOK = "FOK"


# ==========================================================
# Execution Source
# ==========================================================

class ExecutionSource(str, Enum):
    LIVE = "LIVE"
    PAPER = "PAPER"
    BACKTEST = "BACKTEST"


# ==========================================================
# Reject Reason
# ==========================================================

class RejectReason(str, Enum):
    NONE = "NONE"

    INVALID_SYMBOL = "INVALID_SYMBOL"

    INVALID_PRICE = "INVALID_PRICE"

    INVALID_QUANTITY = "INVALID_QUANTITY"

    INSUFFICIENT_BALANCE = "INSUFFICIENT_BALANCE"

    POSITION_ALREADY_EXISTS = "POSITION_ALREADY_EXISTS"

    POSITION_NOT_FOUND = "POSITION_NOT_FOUND"

    SLIPPAGE_TOO_HIGH = "SLIPPAGE_TOO_HIGH"

    MARKET_CLOSED = "MARKET_CLOSED"

    EXCHANGE_ERROR = "EXCHANGE_ERROR"

    NETWORK_ERROR = "NETWORK_ERROR"

    TIMEOUT = "TIMEOUT"

    RISK_MANAGER_REJECTED = "RISK_MANAGER_REJECTED"

    UNKNOWN = "UNKNOWN"


# ==========================================================
# Order Fees
# ==========================================================

@dataclass(slots=True)
class OrderFees:
    """
    جميع الرسوم الخاصة بالأمر.
    """

    exchange_fee: float = 0.0

    network_fee: float = 0.0

    funding_fee: float = 0.0

    borrow_fee: float = 0.0

    other_fee: float = 0.0

    @property
    def total(self) -> float:

        return (

            self.exchange_fee

            + self.network_fee

            + self.funding_fee

            + self.borrow_fee

            + self.other_fee

        )


# ==========================================================
# Slippage Information
# ==========================================================

@dataclass(slots=True)
class SlippageInfo:
    """
    معلومات الانزلاق السعري.
    """

    requested_price: float = 0.0

    executed_price: float = 0.0

    absolute_slippage: float = 0.0

    percent_slippage: float = 0.0

    accepted: bool = True


# ==========================================================
# Retry Policy
# ==========================================================

@dataclass(slots=True)
class RetryPolicy:
    """
    سياسة إعادة المحاولة.
    """

    enabled: bool = True

    max_retry: int = 3

    retry_delay: float = 1.0

    exponential_backoff: bool = True

    max_delay: float = 30.0


# ==========================================================
# Execution Context
# ==========================================================

@dataclass(slots=True)
class ExecutionContext:
    """
    معلومات إضافية مرتبطة بعملية التنفيذ.
    """

    strategy_name: str = ""

    strategy_version: str = ""

    run_id: str = ""

    signal_id: str = ""

    worker_id: str = ""

    exchange_name: str = ""

    source: ExecutionSource = ExecutionSource.LIVE

    created_at: datetime = field(

        default_factory=lambda:

        datetime.now(timezone.utc)

    )

    metadata: dict[str, Any] = field(

        default_factory=dict

    )


# ==========================================================
# Execution Request
# ==========================================================

@dataclass(slots=True)
class ExecutionRequest:
    """
    يمثل طلب تنفيذ واحد ينتقل بين:
    Strategy -> Risk -> Execution -> Exchange
    """

    # ------------------------------------------------------
    # Order Identity
    # ------------------------------------------------------

    symbol: str

    side: OrderSide

    order_type: OrderType = OrderType.MARKET

    # ------------------------------------------------------
    # Prices
    # ------------------------------------------------------

    price: Optional[float] = None

    stop_price: Optional[float] = None

    # ------------------------------------------------------
    # Size
    # ------------------------------------------------------

    quantity: float = 0.0

    quote_quantity: Optional[float] = None

    # ------------------------------------------------------
    # Order Rules
    # ------------------------------------------------------

    time_in_force: TimeInForce = TimeInForce.GTC

    reduce_only: bool = False

    post_only: bool = False

    allow_partial_fill: bool = True

    # ------------------------------------------------------
    # Risk Protection
    # ------------------------------------------------------

    max_slippage: float = 0.002

    timeout_seconds: float = 15.0

    retry_policy: RetryPolicy = field(
        default_factory=RetryPolicy
    )

    # ------------------------------------------------------
    # Runtime
    # ------------------------------------------------------

    created_at: datetime = field(
        default_factory=lambda:
        datetime.now(timezone.utc)
    )

    submitted_at: Optional[datetime] = None

    request_id: str = ""

    client_order_id: str = ""

    # ------------------------------------------------------
    # Context
    # ------------------------------------------------------

    context: ExecutionContext = field(
        default_factory=ExecutionContext
    )

    # ------------------------------------------------------
    # Internal Flags
    # ------------------------------------------------------

    validated: bool = False

    approved_by_risk: bool = False

    submitted: bool = False

    cancelled: bool = False

    expired: bool = False

    # ------------------------------------------------------
    # Helpers
    # ------------------------------------------------------

    @property
    def is_buy(self) -> bool:

        return self.side == OrderSide.BUY

    @property
    def is_sell(self) -> bool:

        return self.side == OrderSide.SELL

    @property
    def is_market(self) -> bool:

        return self.order_type == OrderType.MARKET

    @property
    def is_limit(self) -> bool:

        return self.order_type == OrderType.LIMIT

    @property
    def requires_price(self) -> bool:

        return self.order_type != OrderType.MARKET

    @property
    def has_stop(self) -> bool:

        return self.stop_price is not None

    def mark_validated(self):

        self.validated = True

    def mark_approved(self):

        self.approved_by_risk = True

    def mark_submitted(self):

        self.submitted = True

        self.submitted_at = datetime.now(
            timezone.utc
        )

    def cancel(self):

        self.cancelled = True

    def expire(self):

        self.expired = True


# ==========================================================
# Execution Result
# ==========================================================

@dataclass(slots=True, frozen=True)
class ExecutionResult:
    """
    النتيجة النهائية لعملية تنفيذ أمر.
    هذا الكائن Immutable ولا يجوز تعديله بعد إنشائه.
    """

    # ------------------------------------------------------
    # Identity
    # ------------------------------------------------------

    request_id: str

    client_order_id: str

    exchange_order_id: str = ""

    # ------------------------------------------------------
    # Order
    # ------------------------------------------------------

    symbol: str = ""

    side: OrderSide = OrderSide.BUY

    order_type: OrderType = OrderType.MARKET

    status: OrderStatus = OrderStatus.CREATED

    # ------------------------------------------------------
    # Requested Values
    # ------------------------------------------------------

    requested_price: Optional[float] = None

    requested_quantity: float = 0.0

    # ------------------------------------------------------
    # Executed Values
    # ------------------------------------------------------

    executed_price: float = 0.0

    executed_quantity: float = 0.0

    remaining_quantity: float = 0.0

    average_price: float = 0.0

    # ------------------------------------------------------
    # Financial
    # ------------------------------------------------------

    fees: OrderFees = field(
        default_factory=OrderFees
    )

    slippage: SlippageInfo = field(
        default_factory=SlippageInfo
    )

    # ------------------------------------------------------
    # Reject
    # ------------------------------------------------------

    reject_reason: RejectReason = RejectReason.NONE

    message: str = ""

    # ------------------------------------------------------
    # Timing
    # ------------------------------------------------------

    created_at: datetime = field(
        default_factory=lambda:
        datetime.now(timezone.utc)
    )

    submitted_at: Optional[datetime] = None

    completed_at: Optional[datetime] = None

    latency_ms: float = 0.0

    # ------------------------------------------------------
    # Exchange
    # ------------------------------------------------------

    exchange: str = ""

    raw_response: Optional[dict[str, Any]] = None

    # ------------------------------------------------------
    # Helpers
    # ------------------------------------------------------

    @property
    def is_success(self) -> bool:

        return self.status in (

            OrderStatus.FILLED,

            OrderStatus.PARTIALLY_FILLED,

        )

    @property
    def is_failed(self) -> bool:

        return self.status in (

            OrderStatus.REJECTED,

            OrderStatus.FAILED,

            OrderStatus.EXPIRED,

            OrderStatus.CANCELLED,

        )

    @property
    def fill_ratio(self) -> float:

        if self.requested_quantity <= 0:

            return 0.0

        return min(
            1.0,
            self.executed_quantity / self.requested_quantity
        )

    @property
    def has_partial_fill(self) -> bool:

        return (

            self.executed_quantity > 0

            and

            self.executed_quantity < self.requested_quantity

        )

    @property
    def remaining_ratio(self) -> float:

        if self.requested_quantity <= 0:

            return 0.0

        return max(
            0.0,
            self.remaining_quantity / self.requested_quantity
        )


# ==========================================================
# Fill
# ==========================================================

@dataclass(slots=True, frozen=True)
class Fill:
    """
    يمثل عملية تنفيذ واحدة (Execution Fill).

    قد يتكون الأمر الواحد من عدة Fill عند التنفيذ
    على أكثر من مستوى سعري.
    """

    # ------------------------------------------------------
    # Identity
    # ------------------------------------------------------

    fill_id: str = ""

    trade_id: str = ""

    # ------------------------------------------------------
    # Execution
    # ------------------------------------------------------

    price: float = 0.0

    quantity: float = 0.0

    quote_quantity: float = 0.0

    # ------------------------------------------------------
    # Fees
    # ------------------------------------------------------

    fee: float = 0.0

    fee_asset: str = ""

    # ------------------------------------------------------
    # Liquidity
    # ------------------------------------------------------

    is_maker: bool = False

    is_taker: bool = True

    # ------------------------------------------------------
    # Timestamp
    # ------------------------------------------------------

    executed_at: datetime = field(
        default_factory=lambda:
        datetime.now(timezone.utc)
    )

    # ------------------------------------------------------
    # Helpers
    # ------------------------------------------------------

    @property
    def total_cost(self) -> float:

        return self.price * self.quantity

    @property
    def total_cost_with_fee(self) -> float:

        return (self.price * self.quantity) + self.fee


# ==========================================================
# Fill Utilities
# ==========================================================

def total_fill_quantity(
    fills: tuple[Fill, ...]
) -> float:

    return fsum(
        fill.quantity
        for fill in fills
    )


def total_fill_quote(
    fills: tuple[Fill, ...]
) -> float:

    return fsum(
        fill.quote_quantity
        for fill in fills
    )


def total_fill_fees(
    fills: tuple[Fill, ...]
) -> float:

    return fsum(
        fill.fee
        for fill in fills
    )


def weighted_average_price(
    fills: tuple[Fill, ...]
) -> float:

    total_qty = total_fill_quantity(fills)

    if total_qty <= 0.0:

        return 0.0

    return (

        fsum(

            fill.price * fill.quantity

            for fill in fills

        )

        /

        total_qty

    )


# ==========================================================
# Execution Statistics
# ==========================================================

@dataclass(slots=True)
class ExecutionStatistics:
    """
    إحصائيات أداء محرك التنفيذ.
    """

    # ------------------------------------------------------
    # Counters
    # ------------------------------------------------------

    total_requests: int = 0

    total_submitted: int = 0

    total_filled: int = 0

    total_partial_filled: int = 0

    total_cancelled: int = 0

    total_rejected: int = 0

    total_failed: int = 0

    total_expired: int = 0

    # ------------------------------------------------------
    # Volumes
    # ------------------------------------------------------

    total_volume: float = 0.0

    total_quote_volume: float = 0.0

    # ------------------------------------------------------
    # Costs
    # ------------------------------------------------------

    total_fees: float = 0.0

    average_fee: float = 0.0

    # ------------------------------------------------------
    # Slippage
    # ------------------------------------------------------

    total_slippage: float = 0.0

    average_slippage: float = 0.0

    worst_slippage: float = 0.0

    best_slippage: float = 0.0

    # ------------------------------------------------------
    # Latency
    # ------------------------------------------------------

    total_latency_ms: float = 0.0

    average_latency_ms: float = 0.0

    fastest_latency_ms: float = 0.0

    slowest_latency_ms: float = 0.0

    # ------------------------------------------------------
    # Time
    # ------------------------------------------------------

    started_at: datetime = field(
        default_factory=lambda:
        datetime.now(timezone.utc)
    )

    last_execution: Optional[datetime] = None

    # ------------------------------------------------------
    # Helpers
    # ------------------------------------------------------

    @property
    def success_rate(self) -> float:

        if self.total_requests == 0:

            return 0.0

        return (

            (
                self.total_filled
                +
                self.total_partial_filled
            )

            /

            self.total_requests

        ) * 100.0

    @property
    def failure_rate(self) -> float:

        if self.total_requests == 0:

            return 0.0

        return (

            (
                self.total_failed
                +
                self.total_rejected
                +
                self.total_cancelled
                +
                self.total_expired
            )

            /

            self.total_requests

        ) * 100.0

    def register(self, result: ExecutionResult):

        if result.executed_quantity < 0.0:
            raise ValueError("Negative executed quantity.")

        self.total_requests += 1

        self.last_execution = datetime.now(
            timezone.utc
        )

        if result.status == OrderStatus.SUBMITTED:

            self.total_submitted += 1

        elif result.status == OrderStatus.FILLED:

            self.total_filled += 1

        elif result.status == OrderStatus.PARTIALLY_FILLED:

            self.total_partial_filled += 1

        elif result.status == OrderStatus.REJECTED:

            self.total_rejected += 1

        elif result.status == OrderStatus.CANCELLED:

            self.total_cancelled += 1

        elif result.status == OrderStatus.EXPIRED:

            self.total_expired += 1

        elif result.status == OrderStatus.FAILED:

            self.total_failed += 1

        # التعديل الجديد: اعتماد math.fsum في التجميع المباشر للإحصائيات المتراكمة لضمان دقة float
        self.total_volume = fsum((
            self.total_volume,
            result.executed_quantity,
        ))

        self.total_quote_volume = fsum((
            self.total_quote_volume,
            result.executed_quantity * result.average_price,
        ))

        self.total_fees = fsum((
            self.total_fees,
            result.fees.total,
        ))

        self.total_slippage = fsum((
            self.total_slippage,
            result.slippage.percent_slippage,
        ))

        self.total_latency_ms = fsum((
            self.total_latency_ms,
            result.latency_ms,
        ))

        completed = self.total_filled + self.total_partial_filled

        if completed > 0:

            self.average_fee = (
                self.total_fees
                /
                completed
            )

            self.average_slippage = (
                self.total_slippage
                /
                completed
            )

            self.average_latency_ms = (
                self.total_latency_ms
                /
                completed
            )

        if self.fastest_latency_ms == 0:

            self.fastest_latency_ms = result.latency_ms

        else:

            self.fastest_latency_ms = min(

                self.fastest_latency_ms,

                result.latency_ms,

            )

        self.slowest_latency_ms = max(

            self.slowest_latency_ms,

            result.latency_ms,

        )

        self.worst_slippage = max(

            self.worst_slippage,

            result.slippage.percent_slippage,

        )

        if self.best_slippage == 0:

            self.best_slippage = (

                result.slippage.percent_slippage

            )

        else:

            self.best_slippage = min(

                self.best_slippage,

                result.slippage.percent_slippage,

            )

    def reset(self):

        self.total_requests = 0

        self.total_submitted = 0

        self.total_filled = 0

        self.total_partial_filled = 0

        self.total_cancelled = 0

        self.total_rejected = 0

        self.total_failed = 0

        self.total_expired = 0

        self.total_volume = 0.0

        self.total_quote_volume = 0.0

        self.total_fees = 0.0

        self.average_fee = 0.0

        self.total_slippage = 0.0

        self.average_slippage = 0.0

        self.worst_slippage = 0.0

        self.best_slippage = 0.0

        self.total_latency_ms = 0.0

        self.average_latency_ms = 0.0

        self.fastest_latency_ms = 0.0

        self.slowest_latency_ms = 0.0

        self.started_at = datetime.now(timezone.utc)

        self.last_execution = None
