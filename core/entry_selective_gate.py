"""Selective Paper entry veto derived from the current Entry v2 evidence.

Entry v2 remains advisory. This helper promotes only the small subset of its
signals that showed a clean loss/no-winner separation in the current Paper
sample into a Brain-level Paper veto. It does not change Legacy score
thresholds or any Risk/Trade Manager authority.
"""
from __future__ import annotations

from typing import Any, Mapping

RSI_PRESSURE_THRESHOLD = 49.0


def selective_entry_veto(
    strategy: Mapping[str, Any],
    entry_v2_shadow: Mapping[str, Any] | None,
    *,
    trade_mode: str,
) -> str | None:
    """Return a Brain veto reason for the highest-risk V2 combinations.

    Current calibration evidence (2026-09-26, 23 closed Paper outcomes):
    - SCALP + STRUCTURAL_RECLAIM_NOT_CONFIRMED + 5m RSI >= 49.0: 3 losses,
      0 wins.
    - SCALP + SELLER_PRESSURE_NOT_INVALIDATED + 5m RSI >= 49.0: 1 loss,
      0 wins.
    - SWING + SWING_STRUCTURE_OR_HTF_ALIGNMENT_MISSING + 5m RSI >= 49.0:
      1 loss, 0 wins.

    This is intentionally narrower than making Entry v2 a full gate. The
    remaining V2 rejection reasons stay advisory until a larger sample proves
    they are safe to promote.
    """
    if not isinstance(strategy, Mapping) or not isinstance(entry_v2_shadow, Mapping):
        return None

    lane = str(trade_mode or entry_v2_shadow.get("trade_mode", "NONE")).upper()
    failed_gate = str(entry_v2_shadow.get("failed_gate") or "").upper()
    try:
        rsi5m = float(strategy.get("rsi5m"))
    except (TypeError, ValueError):
        return None

    if rsi5m < RSI_PRESSURE_THRESHOLD:
        return None

    if lane == "SCALP":
        if failed_gate == "STRUCTURAL_RECLAIM_NOT_CONFIRMED":
            return "V2_STRUCTURAL_RECLAIM_RSI_PRESSURE"
        if failed_gate == "SELLER_PRESSURE_NOT_INVALIDATED":
            return "V2_SELLER_PRESSURE_RSI_PRESSURE"

    if lane == "SWING":
        if failed_gate == "SWING_STRUCTURE_OR_HTF_ALIGNMENT_MISSING":
            return "V2_SWING_STRUCTURE_RSI_PRESSURE"

    return None


__all__ = ["RSI_PRESSURE_THRESHOLD", "selective_entry_veto"]
