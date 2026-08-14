"""Part 6 sizing/funding components.

This module preserves the Part-6 responsibilities from the source design while
keeping the canonical Part-8 entry gate in ``risk.RiskManager``.  It is spot-only
and deliberately broker-neutral.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Optional


@dataclass(slots=True)
class PositionSizeResult:
    quantity: float
    position_value: float
    risk_amount: float
    stop_distance: float
    leverage_used: float
    capital_used: float


class PositionSizeCalculator:
    def __init__(self, risk_per_trade_percent: float = 1.0):
        if risk_per_trade_percent <= 0:
            raise ValueError("risk_per_trade_percent must be positive")
        self.risk_per_trade_percent = risk_per_trade_percent

    def calculate(self, *, account_equity: float, entry_price: float,
                  stop_loss: float, leverage: float = 1.0) -> PositionSizeResult:
        if account_equity <= 0 or entry_price <= 0 or stop_loss <= 0:
            raise ValueError("Invalid account equity, entry price or stop loss")
        if leverage <= 0:
            raise ValueError("Invalid leverage")
        stop_distance = abs(entry_price - stop_loss)
        if stop_distance <= 0:
            raise ValueError("Stop distance equals zero")
        risk_amount = account_equity * self.risk_per_trade_percent / 100.0
        quantity = risk_amount / stop_distance
        position_value = quantity * entry_price
        capital_used = position_value / leverage
        return PositionSizeResult(quantity, position_value, risk_amount,
                                  stop_distance, leverage, capital_used)


class PositionSizeNormalizer:
    """Normalize a theoretical quantity against exchange symbol filters."""
    def __init__(self, exchange_info_provider: Any):
        self.exchange_info = exchange_info_provider

    def normalize(self, *, symbol: str, quantity: float, price: float) -> float:
        if quantity <= 0 or price <= 0:
            raise ValueError("quantity and price must be positive")
        filters = self.exchange_info.get_symbol_filters(symbol)
        if filters is None:
            raise ValueError(f"No exchange filters found for {symbol}")
        step = float(filters.step_size)
        minimum = float(filters.min_qty)
        maximum = float(filters.max_qty)
        minimum_notional = float(filters.min_notional)
        if step <= 0:
            raise ValueError("Invalid quantity step")
        quantity = math.floor(quantity / step) * step
        precision = int(getattr(filters, "quantity_precision", 12))
        quantity = round(quantity, precision)
        if quantity < minimum:
            raise ValueError(f"LOT_SIZE_FAILED:{quantity}<{minimum}")
        quantity = min(quantity, maximum)
        if quantity * price < minimum_notional:
            raise ValueError(f"MIN_NOTIONAL_FAILED:{quantity * price:.8f}")
        return quantity


class PositionFundingValidator:
    def __init__(self, maximum_position_size: float = 100000.0,
                 minimum_position_size: float = 10.0):
        self.maximum_position_size = maximum_position_size
        self.minimum_position_size = minimum_position_size

    def validate(self, *, account_equity: float, free_balance: float,
                 position_value: float, capital_required: float,
                 leverage: float = 1.0) -> tuple[bool, str]:
        if account_equity <= 0:
            return False, "INVALID_ACCOUNT_EQUITY"
        if free_balance <= 0:
            return False, "NO_FREE_BALANCE"
        if leverage <= 0 or capital_required <= 0:
            return False, "INVALID_CAPITAL_REQUIRED"
        if capital_required > free_balance:
            return False, "INSUFFICIENT_BALANCE"
        if position_value > self.maximum_position_size:
            return False, "MAX_POSITION_EXCEEDED"
        if position_value < self.minimum_position_size:
            return False, "POSITION_TOO_SMALL"
        return True, "APPROVED"


class AdvancedCapitalValidator:
    def __init__(self, safety_buffer_percent: float = 5.0):
        self.safety_buffer_percent = safety_buffer_percent

    def validate(self, *, free_balance: float, capital_required: float,
                 estimated_fee: float, maintenance_margin: float = 0.0) -> tuple[bool, dict | str]:
        if free_balance <= 0:
            return False, "NO_FREE_BALANCE"
        if capital_required <= 0:
            return False, "INVALID_CAPITAL"
        buffer = free_balance * self.safety_buffer_percent / 100.0
        total = capital_required + estimated_fee + maintenance_margin + buffer
        if total > free_balance:
            return False, "INSUFFICIENT_MARGIN"
        return True, {"remaining_balance": free_balance - total,
                      "capital_required": capital_required,
                      "estimated_fee": estimated_fee,
                      "maintenance_margin": maintenance_margin,
                      "buffer": buffer}


class PositionSizingEngine:
    """Orchestrates calculation, normalization and capital validation."""
    def __init__(self, calculator: PositionSizeCalculator,
                 normalizer: Optional[PositionSizeNormalizer] = None,
                 funding_validator: Optional[PositionFundingValidator] = None,
                 capital_validator: Optional[AdvancedCapitalValidator] = None):
        self.calculator = calculator
        self.normalizer = normalizer
        self.funding_validator = funding_validator or PositionFundingValidator()
        self.capital_validator = capital_validator or AdvancedCapitalValidator()

    def calculate(self, *, symbol: str, entry_price: float, stop_loss: float,
                  account_equity: float, free_balance: float, leverage: float = 1.0,
                  estimated_fee: float = 0.0, maintenance_margin: float = 0.0) -> tuple[bool, Any]:
        result = self.calculator.calculate(account_equity=account_equity,
                                           entry_price=entry_price,
                                           stop_loss=stop_loss,
                                           leverage=leverage)
        if self.normalizer is not None:
            result.quantity = self.normalizer.normalize(symbol=symbol,
                                                        quantity=result.quantity,
                                                        price=entry_price)
            result.position_value = result.quantity * entry_price
            result.capital_used = result.position_value / leverage
        ok, reason = self.funding_validator.validate(
            account_equity=account_equity, free_balance=free_balance,
            position_value=result.position_value, capital_required=result.capital_used,
            leverage=leverage)
        if not ok:
            return False, reason
        ok, capital = self.capital_validator.validate(
            free_balance=free_balance, capital_required=result.capital_used,
            estimated_fee=estimated_fee, maintenance_margin=maintenance_margin)
        if not ok:
            return False, capital
        return True, {"quantity": result.quantity,
                      "position_value": result.position_value,
                      "risk_amount": result.risk_amount,
                      "stop_distance": result.stop_distance,
                      "leverage": result.leverage_used,
                      **capital}
