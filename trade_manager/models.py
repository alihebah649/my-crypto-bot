"""8.1 - Core position models and enums."""
from dataclasses import dataclass, field
from enum import Enum, auto
import time
from typing import Any, Dict, Optional


class PositionStatus(Enum):
    CREATED = auto()
    OPEN = auto()
    PARTIALLY_CLOSED = auto()
    HOLD = auto()
    REVIEW_REQUIRED = auto()
    CLOSED = auto()
    CANCELLED = auto()
    FAILED = auto()


class PositionSide(Enum):
    LONG = auto()  # Spot only


class PositionCloseReason(Enum):
    NONE = auto()
    TAKE_PROFIT = auto()
    STOP_LOSS = auto()
    TRAILING_STOP = auto()
    BREAK_EVEN = auto()
    MANUAL = auto()
    REVIEW_EXIT = auto()
    RECOVERY_FAILED = auto()
    EMERGENCY_EXIT = auto()


@dataclass(slots=True)
class Position:
    position_id: str
    symbol: str
    side: PositionSide
    status: PositionStatus
    quantity: float
    entry_price: float
    current_price: float
    stop_loss: float
    take_profit: Optional[float]
    highest_price: float = 0.0
    lowest_price: float = 0.0
    entered_hold_at: Optional[float] = None
    review_required_at: Optional[float] = None
    max_profit_percent: float = 0.0
    max_drawdown_percent: float = 0.0
    hold_reason: str = ""
    entry_metadata: Dict[str, Any] = field(default_factory=dict)
    exit_metadata: Dict[str, Any] = field(default_factory=dict)
    entry_context: Dict[str, Any] = field(default_factory=dict)
    hold_context: Dict[str, Any] = field(default_factory=dict)
    opened_at: float = field(default_factory=time.time)
    closed_at: Optional[float] = None
    close_reason: PositionCloseReason = PositionCloseReason.NONE
    exchange_order_id: Optional[str] = None
    client_order_id: Optional[str] = None
    gross_pnl: float = 0.0
    realized_pnl: float = 0.0
    total_fees: float = 0.0
    entry_fee: float = 0.0
    exit_fee: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.quantity <= 0 or self.entry_price <= 0:
            raise ValueError("quantity and entry_price must be positive")
        if self.current_price <= 0:
            raise ValueError("current_price must be positive")
        if self.highest_price <= 0:
            self.highest_price = self.entry_price
        if self.lowest_price <= 0:
            self.lowest_price = self.entry_price

    def update_highest_price(self, price: float) -> bool:
        if price > self.highest_price:
            self.highest_price = price
            return True
        return False

    def update_lowest_price(self, price: float) -> bool:
        if price < self.lowest_price:
            self.lowest_price = price
            return True
        return False

    def update_max_profit(self, price: float) -> bool:
        pct = ((price - self.entry_price) / self.entry_price) * 100.0
        if pct > self.max_profit_percent:
            self.max_profit_percent = pct
            return True
        return False

    def update_max_drawdown(self, price: float) -> bool:
        pct = ((self.entry_price - price) / self.entry_price) * 100.0
        if pct > self.max_drawdown_percent:
            self.max_drawdown_percent = pct
            return True
        return False
