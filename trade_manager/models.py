from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, Optional


# ============================================================================
# Part 8 canonical position model
# ============================================================================

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
    """Canonical Part-8 spot position model used by repository/controller/risk/history."""
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
        if price <= 0:
            raise ValueError("price must be positive")
        if price > self.highest_price:
            self.highest_price = price
            return True
        return False

    def update_lowest_price(self, price: float) -> bool:
        if price <= 0:
            raise ValueError("price must be positive")
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


# ============================================================================
# Parts 1-7 compatibility/state model
# ============================================================================

class ProtectionAction(str, Enum):
    NONE = "NONE"
    UPDATE_STOP = "UPDATE_STOP"
    MOVE_TO_BREAK_EVEN = "MOVE_TO_BREAK_EVEN"
    CLOSE_POSITION = "CLOSE_POSITION"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class ExitReason(str, Enum):
    TAKE_PROFIT = "TAKE_PROFIT"
    STOP_LOSS = "STOP_LOSS"
    TRAILING_STOP = "TRAILING_STOP"
    BREAK_EVEN = "BREAK_EVEN"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    MANUAL = "MANUAL"
    RISK_LIMIT = "RISK_LIMIT"
    LIQUIDITY = "LIQUIDITY"
    EXTERNAL = "EXTERNAL"
    ERROR = "ERROR"


@dataclass(slots=True)
class TradeManagerConfig:
    fee_rate: float = 0.001
    slippage_rate: float = 0.0005
    break_even_trigger: float = 0.015
    trailing_activation: float = 0.026
    trailing_atr_multiplier: float = 1.5
    default_atr_stop_multiplier: float = 2.0
    review_after_seconds: float = 7 * 24 * 3600
    max_open_positions: int = 5
    max_symbol_exposure_percent: float = 20.0
    max_portfolio_exposure_percent: float = 80.0
    risk_per_trade_percent: float = 1.0


@dataclass(slots=True)
class ManagedPosition:
    """Part-1-to-7 compatibility model. Part 8 Position is the canonical repository model."""
    symbol: str
    quantity: float
    entry_price: float
    stop_loss: float = 0.0
    take_profit: Optional[float] = None
    atr_at_entry: float = 0.0
    trade_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    opened_at: float = field(default_factory=time.time)
    current_price: float = 0.0
    highest_price: float = 0.0
    lowest_price: float = 0.0
    trailing_active: bool = False
    break_even_done: bool = False
    status: str = "OPEN"
    close_reason: str = ""
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    fees_paid: float = 0.0
    last_update: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.entry_price <= 0 or self.quantity <= 0:
            raise ValueError("Position price and quantity must be positive")
        if self.current_price <= 0:
            self.current_price = self.entry_price
        if self.highest_price <= 0:
            self.highest_price = self.entry_price
        if self.lowest_price <= 0:
            self.lowest_price = self.entry_price

    @property
    def position_value(self) -> float:
        return self.quantity * self.current_price

    @property
    def cost_value(self) -> float:
        return self.quantity * self.entry_price


@dataclass(slots=True)
class TradeContext:
    position: ManagedPosition
    updated_at: float = field(default_factory=time.time)
    recovery_active: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TradeStatistics:
    total_opened: int = 0
    total_closed: int = 0
    total_wins: int = 0
    total_losses: int = 0
    total_review_required: int = 0
    total_realized_pnl: float = 0.0
    total_unrealized_pnl: float = 0.0
    total_fees: float = 0.0
    total_volume: float = 0.0


@dataclass(slots=True)
class ProtectionDecision:
    action: ProtectionAction = ProtectionAction.NONE
    reason: str = "HOLD"
    new_stop_loss: Optional[float] = None
    close_reason: Optional[ExitReason] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RiskEvaluation:
    approved: bool
    reason: str
    risk_percent: float = 0.0
    position_value: float = 0.0
    capital_required: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
