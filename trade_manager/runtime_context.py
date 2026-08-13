"""Runtime context models extracted from Trade Manager Part 1."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass(slots=True)
class TradeContext:
    """Runtime state attached to an active trade."""

    trade: Any
    created_at: float
    updated_at: float
    last_price: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    highest_price: float = 0.0
    lowest_price: float = 0.0
    trailing_active: bool = False
    breakeven_active: bool = False
    recovery_active: bool = False
    partial_closed: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_trade(cls, trade: Any) -> "TradeContext":
        now = time.time()
        entry_price = float(getattr(trade, "entry_price", 0.0) or 0.0)
        return cls(
            trade=trade,
            created_at=now,
            updated_at=now,
            last_price=entry_price,
            highest_price=entry_price,
            lowest_price=entry_price,
        )

    def touch(self) -> None:
        self.updated_at = time.time()
