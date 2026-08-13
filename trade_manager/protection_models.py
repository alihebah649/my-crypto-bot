"""Protection decision models extracted from Trade Manager Part 2.

These models are intentionally independent from the Part 8 position models.
They preserve the Part 2 contract until Parts 3-7 are reconciled.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class TradeSide(Enum):
    LONG = "LONG"
    SHORT = "SHORT"


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
