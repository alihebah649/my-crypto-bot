"""Compare realized shadow outcomes for AI and deterministic decisions."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .brain_shadow_outcome import BrainShadowOutcome


@dataclass(frozen=True)
class BrainVsDeterministicPerformance:
    horizon: str
    sample_size: int
    ai_win_rate: float
    deterministic_win_rate: float
    ai_average_return_percent: float
    deterministic_average_return_percent: float
    ai_better_count: int
    deterministic_better_count: int
    tie_count: int


def compare_realized_outcomes(
    ai_outcomes: Iterable[BrainShadowOutcome],
    deterministic_outcomes: Iterable[BrainShadowOutcome],
) -> list[BrainVsDeterministicPerformance]:
    """Compare only paired outcomes sharing the same context fingerprint/horizon."""
    ai = {(o.context_fingerprint, o.horizon): o for o in ai_outcomes}
    deterministic = {(o.context_fingerprint, o.horizon): o for o in deterministic_outcomes}
    pairs = sorted(set(ai) & set(deterministic), key=lambda key: (key[1], key[0]))

    grouped: dict[str, list[tuple[BrainShadowOutcome, BrainShadowOutcome]]] = {}
    for key in pairs:
        grouped.setdefault(key[1], []).append((ai[key], deterministic[key]))

    result: list[BrainVsDeterministicPerformance] = []
    for horizon, items in sorted(grouped.items()):
        sample_size = len(items)
        ai_better = sum(a.return_percent > d.return_percent for a, d in items)
        det_better = sum(d.return_percent > a.return_percent for a, d in items)
        result.append(
            BrainVsDeterministicPerformance(
                horizon=horizon,
                sample_size=sample_size,
                ai_win_rate=sum(a.favorable for a, _ in items) / sample_size,
                deterministic_win_rate=sum(d.favorable for _, d in items) / sample_size,
                ai_average_return_percent=sum(a.return_percent for a, _ in items) / sample_size,
                deterministic_average_return_percent=sum(d.return_percent for _, d in items) / sample_size,
                ai_better_count=ai_better,
                deterministic_better_count=det_better,
                tie_count=sample_size - ai_better - det_better,
            )
        )
    return result


__all__ = ["BrainVsDeterministicPerformance", "compare_realized_outcomes"]
