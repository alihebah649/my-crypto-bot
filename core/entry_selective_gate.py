"""Selective Paper entry veto derived from the current Entry v2 evidence.

Entry v2 remains advisory. This helper promotes only the small subset of its
signals that showed a clean loss/no-winner separation in the current Paper
sample into a Brain-level Paper veto. It does not change Legacy score
thresholds or any Risk/Trade Manager authority.
"""
from __future__ import annotations

from typing import Any, Mapping

RSI_PRESSURE_THRESHOLD = 49.0
BEAR_SCALP_MIN_VOLUME_RATIO = 1.0


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

    Additional targeted evidence (2026-09-30 to 2026-10-01):
    - HBARUSDT SCALP loss: Entry v2 rejected SELLER_PRESSURE_NOT_INVALIDATED,
      adaptive SCALP regime was BEAR, 5m bias was BEARISH, and 5m volume was
      0.918 (< the existing Entry v2 SCALP minimum of 1.0). Brain's symbol
      regime simultaneously resolved to BULL from higher-timeframe evidence,
      so the local-Bear Brain branch did not apply.
    - A contemporaneous ALGOUSDT SCALP winner had adaptive BEAR classification
      but 5m bias NEUTRAL and volume 1.638, so it does not match this veto.

    The targeted rule below is deliberately narrow: it promotes only this
    exact bearish 5m pressure combination into a Paper Brain veto. It does not
    raise SCALP's 65-point threshold and does not make Entry v2 a full gate.
    """
    if not isinstance(strategy, Mapping) or not isinstance(entry_v2_shadow, Mapping):
        return None

    lane = str(trade_mode or entry_v2_shadow.get("trade_mode", "NONE")).upper()
    failed_gate = str(entry_v2_shadow.get("failed_gate") or "").upper()

    # Preserve the previously calibrated RSI-pressure vetoes first.
    try:
        rsi5m = float(strategy.get("rsi5m"))
    except (TypeError, ValueError):
        return None

    if rsi5m >= RSI_PRESSURE_THRESHOLD:
        if lane == "SCALP":
            if failed_gate == "STRUCTURAL_RECLAIM_NOT_CONFIRMED":
                return "V2_STRUCTURAL_RECLAIM_RSI_PRESSURE"
            if failed_gate == "SELLER_PRESSURE_NOT_INVALIDATED":
                return "V2_SELLER_PRESSURE_RSI_PRESSURE"

        if lane == "SWING":
            if failed_gate == "SWING_STRUCTURE_OR_HTF_ALIGNMENT_MISSING":
                return "V2_SWING_STRUCTURE_RSI_PRESSURE"

    # Narrow Paper-only promotion for the remaining SCALP loophole found in
    # HBAR evidence: Entry v2 says seller pressure is still invalidated, while
    # the adaptive SCALP shadow sees a bearish regime and bearish 5m bias.
    # Volume < 1.0 deliberately reuses Entry v2's existing SCALP volume gate;
    # it is not a new score/strategy threshold.
    if lane == "SCALP" and failed_gate == "SELLER_PRESSURE_NOT_INVALIDATED":
        adaptive = entry_v2_shadow.get("adaptive_scalp_shadow")
        if isinstance(adaptive, Mapping):
            adaptive_regime = str(adaptive.get("regime") or "").upper()
            five_m_bias = str(adaptive.get("five_m_bias") or "").upper()
            try:
                volume_ratio_5m = float(adaptive.get("volume_ratio_5m"))
            except (TypeError, ValueError):
                volume_ratio_5m = None

            if (
                adaptive_regime == "BEAR"
                and five_m_bias == "BEARISH"
                and volume_ratio_5m is not None
                and volume_ratio_5m < BEAR_SCALP_MIN_VOLUME_RATIO
            ):
                return "V2_BEAR_SCALP_5M_PRESSURE_LOW_VOLUME"

    return None


__all__ = [
    "BEAR_SCALP_MIN_VOLUME_RATIO",
    "RSI_PRESSURE_THRESHOLD",
    "selective_entry_veto",
]
