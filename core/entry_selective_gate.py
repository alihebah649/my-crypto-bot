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
BEAR_RECOVERY_MIN_TRIGGERS = 3
BEAR_RECOVERY_CLASSIFICATIONS = {"BEAR_RECOVERY", "BEAR_RECOVERY_CAUTION"}


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

    The targeted rules below are deliberately narrow. They promote only
    structurally bearish combinations that were responsible for the observed
    loss patterns into Paper Brain vetoes. They do not raise SCALP's 65-point
    threshold and do not make Entry v2 a full gate.
    - A BEAR recovery with >=3 recovery triggers but no higher-low on either
      5m or 15m remains a recovery, not a confirmed structural reversal.
    - Seller-pressure rejection plus persistent lower-high structure on both
      5m and 15m is treated as unresolved supply pressure.
    - A 15m higher-low explicitly exempts the first rule, preserving the
      RENDER-style winner where Entry v2 previously missed valid structure.
    """
    if not isinstance(strategy, Mapping) or not isinstance(entry_v2_shadow, Mapping):
        return None

    lane = str(trade_mode or entry_v2_shadow.get("trade_mode", "NONE")).upper()
    # Entry v2 captures have used both the direct field name (`failed_gate`)
    # and the persisted/candidate-capture field name (`v2_failed_gate`).
    # Accept both forms so the selective veto cannot silently become advisory
    # merely because the capture schema uses its prefixed form.
    failed_gate = str(
        entry_v2_shadow.get("failed_gate")
        or entry_v2_shadow.get("v2_failed_gate")
        or ""
    ).upper()

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

    adaptive = entry_v2_shadow.get("adaptive_scalp_shadow")
    if isinstance(adaptive, Mapping):
        adaptive_regime = str(adaptive.get("regime") or "").upper()
        classification = str(adaptive.get("classification") or "").upper()
        five_m_bias = str(adaptive.get("five_m_bias") or "").upper()
        try:
            volume_ratio_5m = float(adaptive.get("volume_ratio_5m"))
        except (TypeError, ValueError):
            volume_ratio_5m = None
        try:
            recovery_trigger_count = int(adaptive.get("recovery_trigger_count") or 0)
        except (TypeError, ValueError):
            recovery_trigger_count = 0

        five_m_patterns = {
            str(item).upper()
            for item in (entry_v2_shadow.get("candle_patterns_5m") or ())
        }
        fifteen_m_patterns = {
            str(item).upper()
            for item in (entry_v2_shadow.get("candle_patterns_15m") or ())
        }
        higher_low = (
            "7C_HIGHER_LOW_STRUCTURE" in five_m_patterns
            or "7C_HIGHER_LOW_STRUCTURE" in fifteen_m_patterns
        )
        persistent_lower_high = (
            "7C_LOWER_HIGH_STRUCTURE" in five_m_patterns
            and "7C_LOWER_HIGH_STRUCTURE" in fifteen_m_patterns
        )

        # Structural no-reclaim veto: this catches the observed NEAR/ETH class
        # where Legacy/Brain saw a high score plus recovery, while Entry v2 saw
        # no structural reclaim. The higher-low check is intentionally inclusive
        # of 15m so a RENDER-style valid reversal is not blocked.
        if (
            lane == "SCALP"
            and failed_gate == "STRUCTURAL_RECLAIM_NOT_CONFIRMED"
            and adaptive_regime == "BEAR"
            and classification in BEAR_RECOVERY_CLASSIFICATIONS
            and recovery_trigger_count >= BEAR_RECOVERY_MIN_TRIGGERS
            and not higher_low
        ):
            return "V2_BEAR_RECOVERY_NO_STRUCTURAL_RECLAIM"

        # Narrow Paper-only promotion for the HBAR class: seller pressure is
        # still active while the adaptive SCALP shadow is bearish on 5m and
        # volume is below Entry v2's existing 1.0 boundary.
        if (
            lane == "SCALP"
            and failed_gate == "SELLER_PRESSURE_NOT_INVALIDATED"
            and adaptive_regime == "BEAR"
            and five_m_bias == "BEARISH"
            and volume_ratio_5m is not None
            and volume_ratio_5m < BEAR_SCALP_MIN_VOLUME_RATIO
        ):
            return "V2_BEAR_SCALP_5M_PRESSURE_LOW_VOLUME"

        # FET-like persistent supply: high volume alone is not enough to call a
        # reversal when both 5m and 15m still print lower-high structure. Requiring
        # both timeframes keeps the veto narrower than a generic BEAR filter and
        # avoids the contemporaneous ALGO winner profile (no persistent dual-TF
        # lower-high evidence).
        if (
            lane == "SCALP"
            and failed_gate == "SELLER_PRESSURE_NOT_INVALIDATED"
            and adaptive_regime == "BEAR"
            and persistent_lower_high
            and not higher_low
        ):
            return "V2_BEAR_SELLER_PRESSURE_DUAL_TF_LOWER_HIGH"

    return None


__all__ = [
    "BEAR_RECOVERY_CLASSIFICATIONS",
    "BEAR_RECOVERY_MIN_TRIGGERS",
    "BEAR_SCALP_MIN_VOLUME_RATIO",
    "RSI_PRESSURE_THRESHOLD",
    "selective_entry_veto",
]
