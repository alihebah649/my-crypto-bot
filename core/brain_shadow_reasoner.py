"""Provider-neutral shadow reasoner contract for future AI implementations."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from .brain_reasoning import BrainDecision, BrainReasoner


class AIReasoningProvider(Protocol):
    """Minimal provider contract; implementations must be side-effect free."""

    def reason(self, context: Mapping[str, Any]) -> BrainDecision:
        ...


@dataclass(frozen=True)
class ShadowReasoningResult:
    ai_decision: BrainDecision
    shadow_only: bool = True


class ShadowAIReasoner(BrainReasoner):
    """Runs an injected AI provider as an observer only.

    This class deliberately returns a BrainDecision but has no execution,
    position, risk, or policy mutation capabilities.
    """

    def __init__(self, provider: AIReasoningProvider):
        self.provider = provider

    def decide(self, context: Mapping[str, Any]) -> BrainDecision:
        return self.provider.reason(context)

    def evaluate_shadow(self, context: Mapping[str, Any]) -> ShadowReasoningResult:
        return ShadowReasoningResult(ai_decision=self.decide(context))


__all__ = ["AIReasoningProvider", "ShadowReasoningResult", "ShadowAIReasoner"]
