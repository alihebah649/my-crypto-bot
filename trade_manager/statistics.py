"""Trade Manager statistics container extracted from Part 1."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(slots=True)
class TradeStatistics:
    total_opened: int = 0
    total_closed: int = 0
    total_archived: int = 0
    total_wins: int = 0
    total_losses: int = 0
    total_recovered: int = 0
    total_partial_closes: int = 0
    total_stoploss: int = 0
    total_takeprofit: int = 0
    total_trailing_exit: int = 0
    total_break_even: int = 0

    total_realized_pnl: float = 0.0
    total_unrealized_pnl: float = 0.0
    total_profit: float = 0.0
    total_loss: float = 0.0
    best_trade: float = 0.0
    worst_trade: float = 0.0
    total_fees: float = 0.0
    total_volume: float = 0.0
    average_holding_time: float = 0.0
    last_statistics_update: Optional[float] = None
