"""8.7 - Closed-position performance metrics."""
from dataclasses import dataclass, field
import threading
import time
from typing import List
from .models import Position


@dataclass(slots=True)
class PositionMetrics:
    total_positions: int = 0
    winning_positions: int = 0
    losing_positions: int = 0
    breakeven_positions: int = 0
    net_pnl: float = 0.0
    total_fees: float = 0.0
    win_rate: float = 0.0
    loss_rate: float = 0.0
    profit_factor_net: float = 0.0
    expectancy_net: float = 0.0
    average_profit: float = 0.0
    average_loss: float = 0.0
    average_roi: float = 0.0
    largest_winner: float = 0.0
    largest_loser: float = 0.0
    average_holding_hours: float = 0.0
    timestamp: float = field(default_factory=time.time)


class PositionMetricsCalculator:
    def calculate(self, positions: List[Position]) -> PositionMetrics:
        closed = [p for p in positions if p.status.name == "CLOSED"]
        m = PositionMetrics(total_positions=len(closed))
        if not closed: return m
        wins = [p.realized_pnl for p in closed if p.realized_pnl > 0]
        losses = [p.realized_pnl for p in closed if p.realized_pnl < 0]
        m.net_pnl = sum(p.realized_pnl for p in closed)
        m.total_fees = sum(p.total_fees for p in closed)
        m.winning_positions = len(wins); m.losing_positions = len(losses)
        m.breakeven_positions = len(closed) - len(wins) - len(losses)
        m.win_rate = m.winning_positions / len(closed) * 100.0
        m.loss_rate = m.losing_positions / len(closed) * 100.0
        m.average_profit = sum(wins) / len(wins) if wins else 0.0
        m.average_loss = sum(losses) / len(losses) if losses else 0.0
        gross_wins = sum(wins); gross_losses = abs(sum(losses))
        m.profit_factor_net = gross_wins / gross_losses if gross_losses else (float("inf") if gross_wins else 0.0)
        m.expectancy_net = m.net_pnl / len(closed)
        m.largest_winner = max(wins, default=0.0)
        m.largest_loser = min(losses, default=0.0)
        rois = []
        holds = []
        for p in closed:
            cost = p.entry_price * p.quantity
            if cost > 0: rois.append(p.realized_pnl / cost * 100.0)
            if p.closed_at: holds.append((p.closed_at - p.opened_at) / 3600.0)
        m.average_roi = sum(rois) / len(rois) if rois else 0.0
        m.average_holding_hours = sum(holds) / len(holds) if holds else 0.0
        m.timestamp = time.time()
        return m


class PositionMetricsService:
    def __init__(self, history_service):
        self.history_service = history_service
        self._calculator = PositionMetricsCalculator()
        self._metrics = PositionMetrics()
        self._lock = threading.RLock()

    def refresh(self) -> None:
        with self._lock:
            self._metrics = self._calculator.calculate(self.history_service.get_all_closed_positions())

    def get_metrics(self) -> PositionMetrics:
        with self._lock: return self._metrics
