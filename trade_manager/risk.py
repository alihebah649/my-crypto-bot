from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from .models import RiskEvaluation


@dataclass(slots=True)
class RiskConfig:
    """Canonical Part-6 entry-risk configuration for spot trading."""
    max_daily_loss_percent: float = 5.0
    max_weekly_loss_percent: float = 10.0
    max_monthly_loss_percent: float = 20.0
    max_open_positions: int = 5
    max_symbol_exposure_percent: float = 20.0
    max_portfolio_exposure_percent: float = 80.0
    max_risk_per_trade_percent: float = 1.0
    maximum_position_size: float = 100000.0
    minimum_position_size: float = 10.0
    maximum_spread_percent: float = 0.30
    maximum_slippage_percent: float = 0.20
    safety_buffer_percent: float = 5.0
    enable_daily_loss_control: bool = True
    enable_weekly_loss_control: bool = True
    enable_monthly_loss_control: bool = True


@dataclass(slots=True)
class LossStatistics:
    daily_pnl: float = 0.0
    weekly_pnl: float = 0.0
    monthly_pnl: float = 0.0
    consecutive_losses: int = 0
    total_closed_trades: int = 0
    total_winning_trades: int = 0
    total_losing_trades: int = 0
    last_trade_timestamp: float = 0.0


class LossTracker:
    """Records closed-trade P&L only; it never makes trading decisions."""

    def __init__(self) -> None:
        self.stats = LossStatistics()
        self._lock = threading.RLock()

    def register_trade(self, pnl: float) -> None:
        with self._lock:
            self.stats.total_closed_trades += 1
            self.stats.daily_pnl += pnl
            self.stats.weekly_pnl += pnl
            self.stats.monthly_pnl += pnl
            self.stats.last_trade_timestamp = time.time()
            if pnl >= 0:
                self.stats.total_winning_trades += 1
                self.stats.consecutive_losses = 0
            else:
                self.stats.total_losing_trades += 1
                self.stats.consecutive_losses += 1

    def reset_daily(self) -> None:
        with self._lock:
            self.stats.daily_pnl = 0.0

    def reset_weekly(self) -> None:
        with self._lock:
            self.stats.weekly_pnl = 0.0

    def reset_monthly(self) -> None:
        with self._lock:
            self.stats.monthly_pnl = 0.0

    def snapshot(self) -> LossStatistics:
        with self._lock:
            return LossStatistics(**self.stats.__dict__) if hasattr(self.stats, "__dict__") else LossStatistics(
                daily_pnl=self.stats.daily_pnl,
                weekly_pnl=self.stats.weekly_pnl,
                monthly_pnl=self.stats.monthly_pnl,
                consecutive_losses=self.stats.consecutive_losses,
                total_closed_trades=self.stats.total_closed_trades,
                total_winning_trades=self.stats.total_winning_trades,
                total_losing_trades=self.stats.total_losing_trades,
                last_trade_timestamp=self.stats.last_trade_timestamp,
            )


class DailyRiskManager:
    def __init__(self, config: RiskConfig, loss_tracker: LossTracker):
        self.config = config
        self.loss_tracker = loss_tracker

    def evaluate(self, account_equity: float) -> tuple[bool, dict[str, Any] | str]:
        if account_equity <= 0:
            return False, "INVALID_ACCOUNT"
        loss = max(0.0, -self.loss_tracker.snapshot().daily_pnl)
        limit = account_equity * self.config.max_daily_loss_percent / 100.0
        if self.config.enable_daily_loss_control and loss >= limit:
            return False, "DAILY_LOSS_LIMIT"
        return True, {"loss": loss, "limit": limit, "remaining": max(0.0, limit - loss)}


class WeeklyRiskManager:
    def __init__(self, config: RiskConfig, loss_tracker: LossTracker):
        self.config = config
        self.loss_tracker = loss_tracker

    def evaluate(self, account_equity: float) -> tuple[bool, dict[str, Any] | str]:
        if account_equity <= 0:
            return False, "INVALID_ACCOUNT"
        loss = max(0.0, -self.loss_tracker.snapshot().weekly_pnl)
        limit = account_equity * self.config.max_weekly_loss_percent / 100.0
        if self.config.enable_weekly_loss_control and loss >= limit:
            return False, "WEEKLY_LOSS_LIMIT"
        return True, {"loss": loss, "limit": limit, "remaining": max(0.0, limit - loss)}


class MonthlyRiskManager:
    def __init__(self, config: RiskConfig, loss_tracker: LossTracker):
        self.config = config
        self.loss_tracker = loss_tracker

    def evaluate(self, account_equity: float) -> tuple[bool, dict[str, Any] | str]:
        if account_equity <= 0:
            return False, "INVALID_ACCOUNT"
        loss = max(0.0, -self.loss_tracker.snapshot().monthly_pnl)
        limit = account_equity * self.config.max_monthly_loss_percent / 100.0
        if self.config.enable_monthly_loss_control and loss >= limit:
            return False, "MONTHLY_LOSS_LIMIT"
        return True, {"loss": loss, "limit": limit, "remaining": max(0.0, limit - loss)}


@dataclass(slots=True)
class RiskLockState:
    locked: bool = False
    reason: str = ""
    locked_at: float = 0.0
    unlock_at: Optional[float] = None


class RiskLockManager:
    """Thread-safe lock used by the entry gate; it never closes an open position."""

    def __init__(self) -> None:
        self._state = RiskLockState()
        self._lock = threading.RLock()

    def lock(self, reason: str, unlock_at: Optional[float] = None) -> None:
        with self._lock:
            self._state = RiskLockState(True, reason, time.time(), unlock_at)

    def unlock(self) -> None:
        with self._lock:
            self._state = RiskLockState()

    def is_locked(self) -> bool:
        with self._lock:
            if self._state.locked and self._state.unlock_at is not None and time.time() >= self._state.unlock_at:
                self._state = RiskLockState()
            return self._state.locked

    def reason(self) -> str:
        with self._lock:
            return self._state.reason

    def snapshot(self) -> RiskLockState:
        with self._lock:
            return RiskLockState(self._state.locked, self._state.reason,
                                 self._state.locked_at, self._state.unlock_at)


class RiskManager:
    """Part-6 entry gate: sizing, exposure, market filters and loss controls."""

    def __init__(self, config: RiskConfig | None = None,
                 loss_tracker: LossTracker | None = None,
                 risk_lock: RiskLockManager | None = None) -> None:
        self.config = config or RiskConfig()
        self.loss_tracker = loss_tracker or LossTracker()
        self.risk_lock = risk_lock or RiskLockManager()
        self.daily = DailyRiskManager(self.config, self.loss_tracker)
        self.weekly = WeeklyRiskManager(self.config, self.loss_tracker)
        self.monthly = MonthlyRiskManager(self.config, self.loss_tracker)

    def calculate_position_size(self, equity: float, entry_price: float,
                                stop_loss: float, free_balance: float) -> float:
        if equity <= 0 or entry_price <= 0 or stop_loss <= 0 or free_balance <= 0:
            return 0.0
        distance = abs(entry_price - stop_loss)
        if distance <= 0:
            return 0.0
        risk_amount = equity * self.config.max_risk_per_trade_percent / 100.0
        quantity = risk_amount / distance
        value = min(quantity * entry_price, self.config.maximum_position_size, free_balance)
        return max(0.0, value)

    def evaluate(self, *, equity: float, free_balance: float, entry_price: float, stop_loss: float,
                 open_positions: int, current_exposure: float, symbol_exposure: float = 0.0,
                 estimated_fee: float = 0.0, spread_percent: float = 0.0,
                 slippage_percent: float = 0.0, risk_percent: float | None = None) -> RiskEvaluation:
        if equity <= 0:
            return RiskEvaluation(False, "INVALID_ACCOUNT_EQUITY")
        if free_balance <= 0:
            return RiskEvaluation(False, "NO_FREE_BALANCE")
        if self.risk_lock.is_locked():
            return RiskEvaluation(False, f"RISK_LOCK:{self.risk_lock.reason()}")
        if entry_price <= 0 or stop_loss <= 0 or entry_price == stop_loss:
            return RiskEvaluation(False, "INVALID_STOP_DISTANCE")
        if stop_loss >= entry_price:
            return RiskEvaluation(False, "INVALID_SPOT_STOP")
        if open_positions >= self.config.max_open_positions:
            return RiskEvaluation(False, "MAX_OPEN_POSITIONS")
        if symbol_exposure >= self.config.max_symbol_exposure_percent:
            return RiskEvaluation(False, "MAX_SYMBOL_EXPOSURE")

        for checker in (self.daily, self.weekly, self.monthly):
            ok, result = checker.evaluate(equity)
            if not ok:
                return RiskEvaluation(False, str(result))

        risk_pct = self.config.max_risk_per_trade_percent if risk_percent is None else risk_percent
        if risk_pct <= 0 or risk_pct > self.config.max_risk_per_trade_percent:
            return RiskEvaluation(False, "INVALID_RISK_PERCENT")

        stop_distance = abs(entry_price - stop_loss)
        risk_amount = equity * risk_pct / 100.0
        quantity = risk_amount / stop_distance
        position_value = quantity * entry_price
        position_value = min(position_value, self.config.maximum_position_size)

        if position_value < self.config.minimum_position_size:
            return RiskEvaluation(False, "POSITION_TOO_SMALL", risk_pct, position_value)
        if spread_percent > self.config.maximum_spread_percent:
            return RiskEvaluation(False, "SPREAD_TOO_HIGH", risk_pct, position_value)
        if slippage_percent > self.config.maximum_slippage_percent:
            return RiskEvaluation(False, "SLIPPAGE_TOO_HIGH", risk_pct, position_value)

        safety_buffer = free_balance * self.config.safety_buffer_percent / 100.0
        required = position_value + estimated_fee + safety_buffer
        if required > free_balance:
            return RiskEvaluation(False, "INSUFFICIENT_BALANCE", risk_pct, position_value,
                                   required, {"safety_buffer": safety_buffer})

        max_exposure = equity * self.config.max_portfolio_exposure_percent / 100.0
        if current_exposure + position_value > max_exposure:
            return RiskEvaluation(False, "MAX_PORTFOLIO_EXPOSURE", risk_pct, position_value)
        if not math.isfinite(position_value) or position_value <= 0:
            return RiskEvaluation(False, "INVALID_POSITION_SIZE")

        return RiskEvaluation(True, "APPROVED", risk_pct, position_value, required,
                              {"stop_distance": stop_distance,
                               "risk_amount": risk_amount,
                               "safety_buffer": safety_buffer,
                               "quantity": quantity})
