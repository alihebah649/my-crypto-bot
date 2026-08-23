"""Safety gate between Brain recommendations and authoritative execution policy."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class SafetyDecision:
    action: str
    authority: str
    allowed: bool
    reason: str


class BrainSafetyGate:
    """Never lets a Brain recommendation weaken authoritative safety rules."""

    def evaluate(
        self,
        brain_action: str,
        *,
        hard_stop_triggered: bool = False,
        take_profit_triggered: bool = False,
        risk_locked: bool = False,
        policy_action: str = "HOLD",
        execution_allowed: bool = True,
        context: Mapping[str, Any] | None = None,
    ) -> SafetyDecision:
        brain = str(brain_action or "HOLD").upper()
        policy = str(policy_action or "HOLD").upper()

        if hard_stop_triggered:
            return SafetyDecision("EXIT", "HARD_STOP", True, "HARD_STOP_AUTHORITATIVE")
        if take_profit_triggered:
            return SafetyDecision("EXIT", "TAKE_PROFIT", True, "TAKE_PROFIT_AUTHORITATIVE")
        if risk_locked:
            return SafetyDecision("BLOCK", "RISK", False, "RISK_LOCKED")
        if not execution_allowed:
            return SafetyDecision("BLOCK", "EXECUTION_GATE", False, "EXECUTION_NOT_ALLOWED")
        if policy in {"EXIT", "SELL"}:
            return SafetyDecision("EXIT", "EXIT_POLICY", True, "EXIT_POLICY_AUTHORITATIVE")
        if brain not in {"BUY", "SELL", "EXIT", "HOLD", "REVIEW", "NO_ACTION"}:
            return SafetyDecision("BLOCK", "SAFETY_GATE", False, "INVALID_BRAIN_ACTION")
        if brain in {"SELL", "EXIT"}:
            return SafetyDecision("EXIT", "BRAIN_ADVISORY", True, "BRAIN_EXIT_RECOMMENDATION")
        return SafetyDecision(brain, "BRAIN_ADVISORY", True, "BRAIN_RECOMMENDATION_ALLOWED")


__all__ = ["BrainSafetyGate", "SafetyDecision"]
