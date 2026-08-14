from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


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
