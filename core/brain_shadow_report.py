"""Aggregate shadow metrics into a conservative evaluation report."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .brain_shadow_aggregator import ShadowPerformance


@dataclass(frozen=True)
class ShadowEvaluationReport:
    sample_size: int
    eligible: bool
    ai_win_rate: float
    deterministic_win_rate: float
    ai_average_return_percent: float
    deterministic_average_return_percent: float
    ai_wins: int
    deterministic_wins: int
    ties: int


def build_shadow_evaluation_report(
    comparisons: Iterable[dict],
    *,
    min_sample_size: int = 30,
) -> ShadowEvaluationReport:
    rows = list(comparisons)
    if min_sample_size < 1:
        raise ValueError("min_sample_size must be positive")
    if not rows:
        return ShadowEvaluationReport(0, False, 0.0, 0.0, 0.0, 0.0, 0, 0, 0)

    ai_wins = sum(1 for row in rows if row.get("winner") == "AI")
    deterministic_wins = sum(1 for row in rows if row.get("winner") == "DETERMINISTIC")
    ties = sum(1 for row in rows if row.get("winner") == "TIE")
    ai_returns = [float(row["ai_return_percent"]) for row in rows if "ai_return_percent" in row]
    det_returns = [float(row["deterministic_return_percent"]) for row in rows if "deterministic_return_percent" in row]
    ai_favorable = sum(1 for value in ai_returns if value > 0)
    det_favorable = sum(1 for value in det_returns if value > 0)

    return ShadowEvaluationReport(
        sample_size=len(rows),
        eligible=len(rows) >= min_sample_size,
        ai_win_rate=ai_favorable / len(ai_returns) if ai_returns else 0.0,
        deterministic_win_rate=det_favorable / len(det_returns) if det_returns else 0.0,
        ai_average_return_percent=sum(ai_returns) / len(ai_returns) if ai_returns else 0.0,
        deterministic_average_return_percent=sum(det_returns) / len(det_returns) if det_returns else 0.0,
        ai_wins=ai_wins,
        deterministic_wins=deterministic_wins,
        ties=ties,
    )


__all__ = ["ShadowEvaluationReport", "build_shadow_evaluation_report"]
