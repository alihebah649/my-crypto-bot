"""Canonical integration contract between Trade Manager Parts 6, 7 and 8.

Part 6 = entry-risk gate.
Part 7 = execution boundary.
Part 8 = canonical open-position lifecycle.

This module contains contracts only; it does not duplicate strategy logic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from .execution import ExecutionOrder, ExecutionResult
from .models import Position, RiskEvaluation


@dataclass(slots=True)
class EntryIntent:
    symbol: str
    entry_price: float
    stop_loss: float
    quantity: float
    equity: float
    free_balance: float
    current_exposure: float = 0.0
    symbol_exposure: float = 0.0
    spread_percent: float = 0.0
    slippage_percent: float = 0.0
    estimated_fee: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class EntryResult:
    approved: bool
    risk: RiskEvaluation
    execution: ExecutionResult | None = None
    position: Position | None = None
    message: str = ""


class EntryRiskGate(Protocol):
    def evaluate(self, **kwargs: Any) -> RiskEvaluation: ...


class EntryExecutor(Protocol):
    def execute(self, order: ExecutionOrder) -> ExecutionResult: ...


class PositionLifecycle(Protocol):
    def open_position(self, symbol: str, quantity: float, entry_price: float,
                      stop_loss: float, take_profit: float | None = None,
                      entry_metadata: dict | None = None, **kwargs: Any) -> Position: ...


INTEGRATION_ORDER = (
    "SIGNAL",
    "PART6_ENTRY_RISK",
    "PART7_EXECUTION",
    "PART8_POSITION_OPEN",
    "PART8_PROTECTION_RECOVERY",
    "PART7_EXECUTION_EXIT",
    "PART8_POSITION_CLOSE",
    "P&L_HISTORY",
)
