"""Regime-aware SCALP shadow classifier.

This module is diagnostic only. It never changes Strategy, Risk, Trade Manager,
or Execution authority. It classifies an already-qualified Legacy SCALP
candidate so future Paper outcomes can tell us whether bearish conditions are
where the entry quality deteriorates.

The classifier intentionally does not recreate Entry v2's full gate chain.
SCALP must remain a responsive lane; this layer only labels the context and
identifies higher-risk bearish recoveries.
"""
from __future__ import annotations

from typing import Any, Mapping


RULE_VERSION = 2
SCALP_SCORE_THRESHOLD = 65.0
SCALP_MIN_VOLUME_RATIO = 0.75
STRONG_BEAR_NET_GAP = 25.0


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _norm(value: Any) -> str:
    return str(value or "").upper()


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def derive_scalp_timing_profile(legacy_result: Mapping[str, Any]) -> dict[str, str]:
    """Describe SCALP timing/pattern features without making a trading decision."""
    legacy = _mapping(legacy_result)
    rsi = _float(legacy.get("rsi5m"))

    if rsi < 35.0:
        rsi_phase = "EARLY_DEEP_RECOVERY"
    elif rsi < 45.0:
        rsi_phase = "MID_RECOVERY"
    elif rsi < 55.0:
        rsi_phase = "LATE_RECOVERY"
    else:
        rsi_phase = "AT_OR_ABOVE_SCALP_RSI_LIMIT"

    pattern = _norm(legacy.get("pattern"))
    pattern_family = {
        "BULLISH_BREAKOUT": "BREAKOUT",
        "BULLISH_ENGULFING": "ENGULFING",
        "BULLISH_OUTSIDE": "OUTSIDE",
        "MORNING_STAR": "MORNING_STAR",
    }.get(pattern, "OTHER" if pattern not in {"", "NEUTRAL"} else "NONE")

    combined_signature = f"{rsi_phase}__{pattern_family}"
    return {
        "rsi_phase": rsi_phase,
        "pattern_family": pattern_family,
        "combined_signature": combined_signature,
    }


def _regime(legacy: Mapping[str, Any]) -> tuple[str, bool, bool]:
    """Return (regime, strong_bear, htf_bearish) from captured MTF facts."""
    frame_bias = _mapping(legacy.get("mtf_timeframe_bias"))
    one_h = _norm(frame_bias.get("1h"))
    four_h = _norm(frame_bias.get("4h"))
    fifteen_m = _norm(frame_bias.get("15m"))

    weighted_bear = _float(legacy.get("mtf_weighted_bear"))
    weighted_bull = _float(legacy.get("mtf_weighted_bull"))
    net = _float(legacy.get("mtf_net"), weighted_bull - weighted_bear)

    htf_bearish = bool(legacy.get("mtf_higher_timeframes_bearish")) or (
        one_h == "BEARISH" and four_h == "BEARISH"
    )
    strong_bear = bool(
        htf_bearish
        or (weighted_bear - weighted_bull) >= STRONG_BEAR_NET_GAP
        or net <= -STRONG_BEAR_NET_GAP
    )

    if strong_bear:
        return "BEAR", True, htf_bearish
    if _norm(legacy.get("mtf_bias")) == "BEARISH" or fifteen_m == "BEARISH" or net < 0:
        return "BEAR", False, htf_bearish
    if _norm(legacy.get("mtf_bias")) == "BULLISH" or net > 0:
        return "BULL", False, htf_bearish
    return "TRANSITION", False, htf_bearish


def classify_adaptive_scalp(
    legacy_result: Mapping[str, Any],
    scenario: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Classify one Legacy SCALP candidate without making an execution decision."""
    legacy = _mapping(legacy_result)
    scenario_map = _mapping(scenario)
    mode = _norm(legacy.get("trade_mode") or scenario_map.get("trade_mode"))

    timing_profile = derive_scalp_timing_profile(legacy)

    base: dict[str, Any] = {
        "rule_version": RULE_VERSION,
        "trade_mode": mode or "UNKNOWN",
        "candidate": bool(legacy.get("scalp_signal") == "BUY" or mode == "SCALP"),
        "legacy_score": _float(legacy.get("scalp_score", legacy.get("score"))),
        "regime": "UNKNOWN",
        "strong_bear": False,
        "htf_bearish": False,
        "classification": "NOT_APPLICABLE",
        "advisory_action": "NO_ACTION",
        "reasons": [],
        "timing_profile": timing_profile,
    }

    if mode != "SCALP":
        return base

    regime, strong_bear, htf_bearish = _regime(legacy)
    recovery = bool(
        legacy.get("scalp_recovery_confirmation")
        or _mapping(scenario_map.get("trigger")).get("rsi_recovering")
    )
    confirmed_reversal = bool(
        legacy.get("scalp_confirmed_reversal")
        or _mapping(scenario_map.get("trigger")).get("confirmed_reversal")
    )
    trigger_count = int(
        _float(
            legacy.get(
                "scalp_recovery_trigger_count",
                len(legacy.get("scalp_recovery_trigger_reasons", []) or []),
            )
        )
    )
    volume = _float(
        legacy.get(
            "volume_ratio_5m",
            _mapping(scenario_map.get("trigger")).get("volume_ratio_5m"),
        )
    )
    score = _float(legacy.get("scalp_score", legacy.get("score")))
    five_m_bias = _norm(
        _mapping(legacy.get("mtf_timeframe_bias")).get("5m")
        or _mapping(scenario_map.get("market")).get("5m_bias")
    )
    pattern_confirmed = bool(
        legacy.get("pattern_confirmed")
        or _mapping(scenario_map.get("trigger")).get("bullish_pattern")
    )

    base.update({
        "regime": regime,
        "strong_bear": strong_bear,
        "htf_bearish": htf_bearish,
        "recovery_confirmation": recovery,
        "confirmed_reversal": confirmed_reversal,
        "recovery_trigger_count": trigger_count,
        "volume_ratio_5m": volume,
        "five_m_bias": five_m_bias,
        "bullish_pattern_confirmed": pattern_confirmed,
    })

    reasons: list[str] = []
    if score < SCALP_SCORE_THRESHOLD:
        reasons.append("LEGACY_SCALP_SCORE_BELOW_THRESHOLD")
    if volume < SCALP_MIN_VOLUME_RATIO:
        reasons.append("5M_VOLUME_BELOW_LEGACY_MIN")
    if not recovery and not confirmed_reversal:
        reasons.append("NO_RECOVERY_OR_REVERSAL")
    if not pattern_confirmed:
        reasons.append("NO_CONFIRMED_BULLISH_PATTERN")

    if regime != "BEAR":
        base["classification"] = "NORMAL_SCALP"
        base["advisory_action"] = "PASSIVE_SHADOW"
        base["reasons"] = reasons or ["NON_BEAR_REGIME"]
        return base

    if strong_bear:
        strong_recovery = bool(
            recovery
            and trigger_count >= 3
            and volume >= 1.0
            and five_m_bias == "BULLISH"
            and (confirmed_reversal or pattern_confirmed)
        )
        if strong_recovery:
            base["classification"] = "BEAR_RECOVERY_STRONG"
            base["advisory_action"] = "PASSIVE_SHADOW"
            reasons.extend([
                "STRONG_BEAR_BUT_5M_RECOVERY_CONFIRMED",
                "5M_VOLUME_CONFIRMED",
                "5M_BULLISH_BIAS",
            ])
        elif recovery and trigger_count >= 3:
            base["classification"] = "BEAR_RECOVERY_CAUTION"
            base["advisory_action"] = "CAUTION_SHADOW"
            reasons.append("BEAR_RECOVERY_NEEDS_MORE_CONFIRMATION")
        else:
            base["classification"] = "BEAR_HIGH_RISK"
            base["advisory_action"] = "HOLD_SHADOW"
            reasons.append("STRONG_BEAR_WITHOUT_STRONG_RECOVERY")
        base["reasons"] = reasons
        return base

    if confirmed_reversal and recovery:
        base["classification"] = "BEAR_RECOVERY"
        base["advisory_action"] = "PASSIVE_SHADOW"
        reasons.append("BEAR_RECOVERY_CONFIRMED")
    elif recovery:
        base["classification"] = "BEAR_WEAK_RECOVERY"
        base["advisory_action"] = "CAUTION_SHADOW"
        reasons.append("BEAR_RECOVERY_NOT_STRUCTURALLY_CONFIRMED")
    else:
        base["classification"] = "BEAR_HIGH_RISK"
        base["advisory_action"] = "HOLD_SHADOW"
        reasons.append("BEAR_WITHOUT_RECOVERY_CONFIRMATION")

    base["reasons"] = reasons
    return base


__all__ = ["RULE_VERSION", "classify_adaptive_scalp", "derive_scalp_timing_profile"]
