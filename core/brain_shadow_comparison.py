"""Compare Brain shadow decisions without changing execution authority."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from .brain_context_fingerprint import brain_context_fingerprint
from .brain_reasoning import BrainDecision


@dataclass(frozen=True)
class BrainShadowComparison:
    context_fingerprint: str
    symbol: str
    deterministic_action: str
    ai_action: str
    policy_action: str | None
    deterministic_confidence: float
    ai_confidence: float
    brain_agrees: bool
    ai_agrees_with_policy: bool | None
    deterministic_agrees_with_policy: bool | None
    disagreement_reason: str | None
    authority: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compare_shadow_decisions(
    context: Mapping[str, Any],
    deterministic: BrainDecision,
    ai: BrainDecision,
) -> BrainShadowComparison:
    context_data = dict(context)
    policy = context_data.get("exit_policy") or {}
    policy_action = context_data.get("policy_action", policy.get("decision"))
    policy_value = str(policy_action).upper() if policy_action is not None else None
    deterministic_action = str(deterministic.action).upper()
    ai_action = str(ai.action).upper()

    if deterministic_action == ai_action:
        reason = None
    else:
        reason = f"AI={ai_action};DETERMINISTIC={deterministic_action}"

    return BrainShadowComparison(
        context_fingerprint=brain_context_fingerprint(context_data),
        symbol=str(context_data.get("symbol", "")),
        deterministic_action=deterministic_action,
        ai_action=ai_action,
        policy_action=policy_value,
        deterministic_confidence=float(deterministic.confidence),
        ai_confidence=float(ai.confidence),
        brain_agrees=deterministic_action == ai_action,
        ai_agrees_with_policy=(ai_action == policy_value if policy_value else None),
        deterministic_agrees_with_policy=(
            deterministic_action == policy_value if policy_value else None
        ),
        disagreement_reason=reason,
        authority="POLICY",
    )


__all__ = ["BrainShadowComparison", "compare_shadow_decisions"]
