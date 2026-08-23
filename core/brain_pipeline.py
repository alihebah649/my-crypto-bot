"""End-to-end Brain decision pipeline.

The pipeline composes reasoning and safety without executing trades or mutating
trading state. Execution remains outside this module.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .brain_reasoning import BrainDecision, BrainReasoner
from .brain_safety_gate import BrainSafetyGate


@dataclass(frozen=True)
class BrainPipelineResult:
    brain_decision: BrainDecision
    final_action: str
    authority: str
    blocked: bool
    reason: str


class BrainDecisionPipeline:
    def __init__(self, reasoner: BrainReasoner, safety_gate: BrainSafetyGate | None = None):
        self.reasoner = reasoner
        self.safety_gate = safety_gate or BrainSafetyGate()

    def evaluate(self, context: Mapping[str, Any]) -> BrainPipelineResult:
        decision = self.reasoner.decide(context)
        context_data = dict(context)
        safe = self.safety_gate.evaluate(
            decision.action,
            hard_stop_triggered=bool(context_data.get("hard_stop_triggered", False)),
            take_profit_triggered=bool(context_data.get("take_profit_triggered", False)),
            risk_locked=bool(context_data.get("risk_locked", False)),
            policy_action=str(
                context_data.get("policy_action", context_data.get("exit_policy", {}).get("decision", "HOLD"))
            ),
            execution_allowed=bool(context_data.get("execution_allowed", True)),
            context=context_data,
        )
        return BrainPipelineResult(
            brain_decision=decision,
            final_action=safe.action,
            authority=safe.authority,
            blocked=not safe.allowed,
            reason=safe.reason,
        )


__all__ = ["BrainDecisionPipeline", "BrainPipelineResult"]
