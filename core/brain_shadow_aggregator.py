"""Aggregate shadow outcomes into comparable performance metrics."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .brain_shadow_outcome import BrainShadowOutcome


@dataclass(frozen=True)
class ShadowPerformance:
    action: str
    horizon: str
    sample_size: int
    favorable_count: int
    win_rate: float
    average_return_percent: float


def aggregate_shadow_outcomes(outcomes: Iterable[BrainShadowOutcome]) -> list[ShadowPerformance]:
    groups: dict[tuple[str, str], list[BrainShadowOutcome]] = {}
    for outcome in outcomes:
        key = (outcome.action.upper(), outcome.horizon)
        groups.setdefault(key, []).append(outcome)

    result: list[ShadowPerformance] = []
    for (action, horizon), items in sorted(groups.items()):
        sample_size = len(items)
        favorable_count = sum(1 for item in items if item.favorable)
        average_return = sum(item.return_percent for item in items) / sample_size
        result.append(
            ShadowPerformance(
                action=action,
                horizon=horizon,
                sample_size=sample_size,
                favorable_count=favorable_count,
                win_rate=favorable_count / sample_size,
                average_return_percent=average_return,
            )
        )
    return result


__all__ = ["ShadowPerformance", "aggregate_shadow_outcomes"]
