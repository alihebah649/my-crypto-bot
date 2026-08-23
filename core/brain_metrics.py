"""Metrics for measuring Brain shadow-mode decisions.

The metrics layer is observational only. It never changes a trading decision,
position state, risk state, or execution outcome.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass
class BrainMetrics:
    total_decisions: int = 0
    agreements: int = 0
    disagreements: int = 0
    policy_sells: int = 0
    brain_sells: int = 0
    brain_holds: int = 0
    brain_reviews: int = 0
    authoritative_overrides: int = 0

    def record(self, *, brain_action: str, policy_exit: bool, review_required: bool) -> None:
        self.total_decisions += 1
        action = str(brain_action or "").upper()
        if policy_exit:
            self.policy_sells += 1
        if action == "SELL":
            self.brain_sells += 1
        elif action == "HOLD":
            self.brain_holds += 1
        elif action == "REVIEW":
            self.brain_reviews += 1

        if review_required:
            return
        if (action == "SELL") == bool(policy_exit):
            self.agreements += 1
        else:
            self.disagreements += 1
            if policy_exit:
                self.authoritative_overrides += 1

    def snapshot(self) -> Dict[str, int]:
        return {
            "total_brain_decisions": self.total_decisions,
            "agreements": self.agreements,
            "disagreements": self.disagreements,
            "exit_policy_sells": self.policy_sells,
            "brain_suggested_sells": self.brain_sells,
            "brain_suggested_holds": self.brain_holds,
            "brain_suggested_reviews": self.brain_reviews,
            "authoritative_overrides": self.authoritative_overrides,
        }
