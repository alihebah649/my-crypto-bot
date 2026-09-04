"""Small fail-closed gate for live startup reconciliation."""
from __future__ import annotations

from dataclasses import dataclass

from core.binance_reconciliation import ReconciliationResult


@dataclass(frozen=True, slots=True)
class StartupGateDecision:
    allowed: bool
    reason: str


class StartupReconciliationGate:
    """Translate reconciliation state into a safe resume decision."""

    @staticmethod
    def evaluate(result: ReconciliationResult) -> StartupGateDecision:
        if result.safe_to_resume:
            return StartupGateDecision(True, "RECONCILIATION_SAFE")
        return StartupGateDecision(False, "RECONCILIATION_BLOCKED")
