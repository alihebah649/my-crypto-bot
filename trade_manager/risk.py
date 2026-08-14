from __future__ import annotations

import math
from dataclasses import dataclass
from .models import RiskEvaluation, TradeManagerConfig


@dataclass(slots=True)
class RiskConfig:
    max_daily_loss_percent: float = 5.0
    max_weekly_loss_percent: float = 10.0
    max_monthly_loss_percent: float = 20.0
    max_open_positions: int = 5
    max_symbol_exposure_percent: float = 20.0
    max_portfolio_exposure_percent: float = 80.0
    max_risk_per_trade_percent: float = 1.0
    maximum_position_size: float = 100000.0
    minimum_position_size: float = 10.0


class RiskManager:
    """Part 6 integration layer; Spot-safe and independent of execution."""

    def __init__(self, config: RiskConfig | None = None) -> None:
        self.config = config or RiskConfig()

    def calculate_position_size(self, equity: float, entry_price: float, stop_loss: float, free_balance: float) -> float:
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
        if entry_price <= 0 or stop_loss <= 0 or entry_price == stop_loss:
            return RiskEvaluation(False, "INVALID_STOP_DISTANCE")
        if open_positions >= self.config.max_open_positions:
            return RiskEvaluation(False, "MAX_OPEN_POSITIONS")
        if symbol_exposure >= self.config.max_symbol_exposure_percent:
            return RiskEvaluation(False, "MAX_SYMBOL_EXPOSURE")
        stop_distance = abs(entry_price - stop_loss)
        risk_pct = self.config.max_risk_per_trade_percent if risk_percent is None else risk_percent
        if risk_pct <= 0 or risk_pct > self.config.max_risk_per_trade_percent:
            return RiskEvaluation(False, "INVALID_RISK_PERCENT")
        risk_amount = equity * risk_pct / 100.0
        quantity = risk_amount / stop_distance
        position_value = quantity * entry_price
        if position_value < self.config.minimum_position_size:
            return RiskEvaluation(False, "POSITION_TOO_SMALL", risk_pct, position_value)
        if position_value > self.config.maximum_position_size:
            position_value = self.config.maximum_position_size
        if position_value + estimated_fee > free_balance:
            return RiskEvaluation(False, "INSUFFICIENT_BALANCE", risk_pct, position_value)
        if spread_percent > 0.30:
            return RiskEvaluation(False, "SPREAD_TOO_HIGH", risk_pct, position_value)
        if slippage_percent > 0.20:
            return RiskEvaluation(False, "SLIPPAGE_TOO_HIGH", risk_pct, position_value)
        if current_exposure + position_value > equity * self.config.max_portfolio_exposure_percent / 100.0:
            return RiskEvaluation(False, "MAX_PORTFOLIO_EXPOSURE", risk_pct, position_value)
        if not math.isfinite(position_value) or position_value <= 0:
            return RiskEvaluation(False, "INVALID_POSITION_SIZE")
        return RiskEvaluation(True, "APPROVED", risk_pct, position_value,
                              position_value, {"stop_distance": stop_distance, "risk_amount": risk_amount})
