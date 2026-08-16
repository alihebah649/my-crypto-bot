"""Trade Manager Part 5 exit/recovery primitives.

Spot-only: exits are SELL operations against an existing LONG position.
This module validates/calculates an exit and requires an injected execution
gateway for actual broker interaction.
"""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Optional
import time
from .models import PositionCloseReason

class ExitReason(str, Enum):
    TAKE_PROFIT = "TAKE_PROFIT"
    STOP_LOSS = "STOP_LOSS"
    TRAILING_STOP = "TRAILING_STOP"
    BREAK_EVEN = "BREAK_EVEN"
    MANUAL = "MANUAL"
    REVIEW_EXIT = "REVIEW_EXIT"
    RECOVERY_FAILED = "RECOVERY_FAILED"
    EMERGENCY_EXIT = "EMERGENCY_EXIT"
    ERROR = "ERROR"

@dataclass(frozen=True, slots=True)
class ExitResult:
    success: bool
    position_id: str
    executed_price: float = 0.0
    executed_quantity: float = 0.0
    commission: float = 0.0
    message: str = ""

class ExitValidator:
    def validate(self, position, close_price: float) -> tuple[bool, Optional[str]]:
        if position is None:
            return False, "POSITION_NOT_FOUND"
        if close_price <= 0:
            return False, "INVALID_CLOSE_PRICE"
        if position.quantity <= 0:
            return False, "INVALID_CLOSE_QUANTITY"
        if position.status.name not in {"OPEN", "HOLD", "REVIEW_REQUIRED"}:
            return False, f"INVALID_POSITION_STATUS:{position.status.name}"
        if position.current_price > 0:
            deviation = abs(close_price - position.current_price) / position.current_price
            if deviation > 0.20:
                return False, f"PRICE_DEVIATION_TOO_HIGH:{deviation * 100:.2f}%"
        return True, None

class SpotExitService:
    """Execute and finalize a spot exit through an injected gateway."""
    def __init__(self, execution_gateway, repository, calculator):
        self.execution_gateway = execution_gateway
        self.repository = repository
        self.calculator = calculator
        self.validator = ExitValidator()

    def close(self, position, close_price: float, reason: ExitReason) -> ExitResult:
        valid, error = self.validator.validate(position, close_price)
        if not valid:
            return ExitResult(False, position.position_id if position else "", message=error or "INVALID")
        outcome = self.execution_gateway.close_spot(
            symbol=position.symbol, quantity=position.quantity
        )
        if not outcome.success:
            return ExitResult(False, position.position_id, message=outcome.message)
        position.current_price = outcome.average_price
        calc = self.calculator.calculate(position, outcome.average_price)
        position.status = position.status.__class__.CLOSED
        position.closed_at = time.time()
        position.close_reason = getattr(PositionCloseReason, reason.value, PositionCloseReason.MANUAL)
        position.gross_pnl = calc.gross_pnl
        position.realized_pnl = calc.net_pnl
        position.entry_fee = calc.entry_fee
        position.exit_fee = calc.exit_fee
        position.total_fees = calc.total_fees
        self.repository.update(position)
        return ExitResult(
            True, position.position_id, outcome.average_price,
            outcome.executed_quantity, outcome.commission, "EXIT_EXECUTED"
        )
