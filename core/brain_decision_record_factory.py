"""Create an auditable BrainDecisionRecord from pipeline output."""
from __future__ import annotations

import time
from typing import Any, Mapping

from .brain_context_fingerprint import brain_context_fingerprint
from .brain_decision_record import BrainDecisionRecord
from .brain_pipeline import BrainPipelineResult


def build_brain_decision_record(
    context: Mapping[str, Any],
    result: BrainPipelineResult,
    *,
    timestamp: float | None = None,
) -> BrainDecisionRecord:
    """Build a read-only record without mutating context or pipeline state."""
    context_data = dict(context)
    policy = context_data.get("exit_policy") or {}
    policy_action = context_data.get("policy_action", policy.get("decision"))
    symbol = str(context_data.get("symbol", ""))
    trade_mode = str(context_data.get("trade_mode", "SWING")).upper()
    brain_action = result.brain_decision.action
    return BrainDecisionRecord(
        timestamp=time.time() if timestamp is None else float(timestamp),
        context_fingerprint=brain_context_fingerprint(context_data),
        symbol=symbol,
        trade_mode=trade_mode,
        brain_action=brain_action,
        confidence=float(result.brain_decision.confidence),
        reason=result.brain_decision.reason,
        policy_action=str(policy_action) if policy_action is not None else None,
        final_action=result.final_action,
        authority=result.authority,
        brain_agrees_with_policy=(
            str(brain_action).upper() == str(policy_action).upper()
            if policy_action is not None else None
        ),
        exception=result.brain_decision.exception,
        context=context_data,
    )


__all__ = ["build_brain_decision_record"]
