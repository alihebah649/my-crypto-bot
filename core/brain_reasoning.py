"""Reasoning interface for deterministic and future AI Brain implementations."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class BrainDecision:
    action: str
    confidence: float
    reason: str
    exception: str | None = None


class BrainReasoner(ABC):
    """Common contract. Implementations must not mutate trading state."""

    @abstractmethod
    def decide(self, context: Mapping[str, Any]) -> BrainDecision:
        raise NotImplementedError


class DeterministicBrainReasoner(BrainReasoner):
    """Minimal deterministic baseline used before any AI provider is enabled."""

    def decide(self, context: Mapping[str, Any]) -> BrainDecision:
        policy = dict(context.get("exit_policy", {}) or {})
        forced = str(policy.get("decision", "")).upper()
        if forced in {"EXIT", "SELL"}:
            return BrainDecision("EXIT", 1.0, "EXIT_POLICY_AUTHORITATIVE")
        return BrainDecision("HOLD", 0.5, "NO_AUTHORITATIVE_EXIT")


__all__ = ["BrainDecision", "BrainReasoner", "DeterministicBrainReasoner"]
