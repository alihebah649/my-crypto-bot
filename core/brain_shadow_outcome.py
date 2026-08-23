"""Outcome tracking for Brain shadow decisions.

Analytics only: this module never changes trading authority or executes orders.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from .brain_context_fingerprint import brain_context_fingerprint


@dataclass(frozen=True)
class BrainShadowOutcome:
    context_fingerprint: str
    symbol: str
    action: str
    horizon: str
    entry_price: float
    outcome_price: float
    return_percent: float
    favorable: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def record_shadow_outcome(
    context: Mapping[str, Any],
    *,
    action: str,
    horizon: str,
    entry_price: float,
    outcome_price: float,
) -> BrainShadowOutcome:
    """Record a hypothetical outcome for a shadow action."""
    entry = float(entry_price)
    outcome = float(outcome_price)
    if entry <= 0:
        raise ValueError("entry_price must be positive")

    normalized_action = str(action).upper()
    if normalized_action in {"BUY", "HOLD"}:
        return_percent = ((outcome - entry) / entry) * 100.0
    elif normalized_action in {"SELL", "EXIT"}:
        return_percent = ((entry - outcome) / entry) * 100.0
    else:
        raise ValueError(f"unsupported shadow action: {action}")

    return BrainShadowOutcome(
        context_fingerprint=brain_context_fingerprint(dict(context)),
        symbol=str(context.get("symbol", "")),
        action=normalized_action,
        horizon=str(horizon),
        entry_price=entry,
        outcome_price=outcome,
        return_percent=return_percent,
        favorable=return_percent > 0,
    )


__all__ = ["BrainShadowOutcome", "record_shadow_outcome"]
