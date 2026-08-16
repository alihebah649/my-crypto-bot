"""Trade Manager Part 1 runtime state and statistics.

Source basis: Trade Manager Parts 1-5 document, normalized for the
Part-8 spot-only Position contract. This module owns runtime bookkeeping;
it does not place orders or make exit decisions.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import threading, time
from typing import Any, Callable, Dict, List
from .models import Position

@dataclass(slots=True)
class RuntimeTradeContext:
    position: Position
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
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

@dataclass(slots=True)
class RuntimeStatistics:
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
    total_fees: float = 0.0
    total_volume: float = 0.0
    best_trade: float = 0.0
    worst_trade: float = 0.0

class TradeManagerRuntime:
    """Thread-safe runtime registry used by the legacy Part-1 lifecycle."""
    VERSION = "1.0.0"

    def __init__(self, max_history: int = 5000) -> None:
        self.max_history = max_history
        self.active: Dict[str, RuntimeTradeContext] = {}
        self.closed: Dict[str, RuntimeTradeContext] = {}
        self.history: List[RuntimeTradeContext] = []
        self.price_cache: Dict[str, float] = {}
        self.statistics = RuntimeStatistics()
        self._lock = threading.RLock()
        self._callbacks: Dict[str, List[Callable[[RuntimeTradeContext], None]]] = {}

    def register(self, position: Position) -> RuntimeTradeContext:
        with self._lock:
            if position.position_id in self.active:
                raise ValueError(f"position already active: {position.position_id}")
            ctx = RuntimeTradeContext(
                position=position, last_price=position.current_price,
                highest_price=position.highest_price, lowest_price=position.lowest_price,
            )
            self.active[position.position_id] = ctx
            self.statistics.total_opened += 1
            self._dispatch("position_opened", ctx)
            return ctx

    def close(self, position_id: str) -> RuntimeTradeContext | None:
        with self._lock:
            ctx = self.active.pop(position_id, None)
            if ctx is None:
                return None
            self.closed[position_id] = ctx
            self.history.append(ctx)
            if len(self.history) > self.max_history:
                self.history.pop(0)
            self.statistics.total_closed += 1
            pnl = float(ctx.realized_pnl)
            self.statistics.total_realized_pnl += pnl
            if pnl > 0:
                self.statistics.total_wins += 1
                self.statistics.best_trade = max(self.statistics.best_trade, pnl)
            elif pnl < 0:
                self.statistics.total_losses += 1
                self.statistics.worst_trade = min(self.statistics.worst_trade, pnl)
            self._dispatch("position_closed", ctx)
            return ctx

    def update_price(self, position_id: str, price: float) -> RuntimeTradeContext:
        if price <= 0:
            raise ValueError("price must be positive")
        with self._lock:
            ctx = self.active[position_id]
            ctx.last_price = price
            ctx.updated_at = time.time()
            ctx.position.current_price = price
            ctx.position.update_highest_price(price)
            ctx.position.update_lowest_price(price)
            ctx.unrealized_pnl = (price - ctx.position.entry_price) * ctx.position.quantity
            self.price_cache[ctx.position.symbol] = price
            self.statistics.total_unrealized_pnl = sum(c.unrealized_pnl for c in self.active.values())
            return ctx

    def register_callback(self, event: str, callback: Callable[[RuntimeTradeContext], None]) -> None:
        with self._lock:
            self._callbacks.setdefault(event, []).append(callback)

    def _dispatch(self, event: str, ctx: RuntimeTradeContext) -> None:
        for callback in tuple(self._callbacks.get(event, ())):
            try:
                callback(ctx)
            except Exception:
                continue
