"""Protection decision models from Trade Manager Part 2.

The current integration contract is SPOT ONLY. A trade represented here is
therefore LONG/owned-asset state; short-side behavior is deliberately not part
of this boundary.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

class TradeSide(Enum):
    LONG = "LONG"

class TradeStatus(Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"

class TradeAction(Enum):
    NONE = "NONE"
    CLOSE = "CLOSE"
    STOP_LOSS = "STOP_LOSS"
    UPDATE_STOP = "UPDATE_STOP"
    ACTIVATE_BREAK_EVEN = "ACTIVATE_BREAK_EVEN"

@dataclass
class Trade:
    id: str
    symbol: str
    side: TradeSide
    entry_price: float
    stop_loss: Optional[float]
    take_profit: Optional[float]
    status: TradeStatus = TradeStatus.OPEN
    highest_price: float = field(init=False)
    lowest_price: float = field(init=False)
    trailing_enabled: bool = False
    trailing_active: bool = False
    break_even_enabled: bool = False
    break_even_done: bool = False

    def __post_init__(self) -> None:
        if self.side is not TradeSide.LONG:
            raise ValueError("Trade Manager integration is spot-only; side must be LONG")
        if self.entry_price <= 0:
            raise ValueError("entry_price must be positive")
        self.highest_price = self.entry_price
        self.lowest_price = self.entry_price

@dataclass
class TradeDecision:
    action: TradeAction
    reason: str
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    update_highest: bool = False
    new_highest: Optional[float] = None
    update_lowest: bool = False
    new_lowest: Optional[float] = None
    activate_trailing: bool = False
    break_even_done: Optional[bool] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
