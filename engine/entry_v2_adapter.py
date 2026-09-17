"""Legacy -> Entry v2 adapter.

This module is deliberately a translation boundary. It does not change the
legacy strategy and does not execute trades. It converts the existing
``dual_mode_strategy`` result plus closed-candle context into the facts
consumed by ``EntryEngineV2``.

Important design rule:
- scores/reasons from the legacy strategy remain diagnostics;
- 5m/15m/1h/4h context and 3/5/7/8-candle structure become explicit facts;
- recovery alone never becomes a structural reversal in this adapter.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from multi_candle_context import analyze_multi_candle_context
from multi_timeframe_context import analyze_multi_timeframe_context
from .entry_engine import EntryDecision, EntryEngineV2


@dataclass(frozen=True)
class EntryV2MarketFacts:
    """Inputs required to translate one legacy strategy observation."""

    legacy_result: Mapping[str, Any]
    candles_5m: Sequence[Mapping[str, Any]]
    candles_15m: Sequence[Mapping[str, Any]]
    candles_1h: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    candles_4h: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    stop_distance_percent: float = 0.0
    reward_risk: float = 0.0
    spread_percent: float = 0.0
    prior_exit: str | None = None
    prior_context_fingerprint_same: bool = False
    new_structure_after_prior_stop: bool = False
    btc_guard: str = "PASS"


def _closed(candles: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Drop the currently forming candle, matching the legacy convention."""
    return list(candles[:-1]) if len(candles) > 1 else []


def _bias(mtf: Mapping[str, Any], timeframe: str) -> str:
    frame = mtf.get("frames", {}).get(timeframe, {})
    return str(frame.get("bias", "UNKNOWN")).upper()


def _has_pattern(context: Mapping[str, Any], *names: str) -> bool:
    patterns = set(context.get("patterns", []))
    return any(name in patterns for name in names)


def _location_from_legacy(legacy: Mapping[str, Any]) -> tuple[bool, bool]:
    """Translate legacy support language into explicit location facts."""
    reasons = " ".join(str(x) for x in legacy.get("scalp_reasons", []))
    support = any(token in reasons for token in (
        "BOLLINGER_LOWER_SUPPORT",
        "BOLLINGER_NEAR_SUPPORT",
        "BOLLINGER_LOWER_HALF",
        "MACRO_SUPPORT",
    ))
    pullback = any(token in reasons for token in (
        "PULLBACK",
        "EMA100_TREND",
    )) and not support
    return support, pullback


def build_entry_scenario(facts: EntryV2MarketFacts) -> dict[str, Any]:
    legacy = facts.legacy_result
    c5 = _closed(facts.candles_5m)
    c15 = _closed(facts.candles_15m)
    c1h = _closed(facts.candles_1h)
    c4h = _closed(facts.candles_4h)

    mtf = analyze_multi_timeframe_context({
        "5m": c5,
        "15m": c15,
        "1h": c1h,
        "4h": c4h,
    })
    multi = analyze_multi_candle_context(c5)
    support, pullback = _location_from_legacy(legacy)

    confirmed_reversal = bool(legacy.get("scalp_confirmed_reversal"))
    continuation_break = _has_pattern(
        multi,
        "THREE_BULLISH_ADVANCE",
        "THREE_BULLISH_SOLDIERS",
        "5C_BULLISH_MOMENTUM",
    ) and _bias(mtf, "5m") == "BULLISH"
    pullback_holds = _has_pattern(multi, "7C_HIGHER_LOW_STRUCTURE", "8C_SELL_OFF_TO_RECOVERY")
    higher_low = _has_pattern(multi, "7C_HIGHER_LOW_STRUCTURE")
    reclaim = bool(confirmed_reversal and (
        _has_pattern(multi, "8C_SELL_OFF_TO_RECOVERY", "THREE_BULLISH_ADVANCE")
        or str(legacy.get("scalp_recovery_confirmation", False)).lower() == "false"
    ))

    # A legacy recovery flag is intentionally *not* mapped to higher_low or
    # reclaim. This is the central protection against buying a fake recovery.
    if not confirmed_reversal:
        higher_low = False
        reclaim = False

    bearish_weak_recovery = (
        all(_bias(mtf, tf) == "BEARISH" for tf in ("15m", "1h", "4h"))
        and not confirmed_reversal
    )

    mode = str(legacy.get("trade_mode", "NONE")).upper()
    if mode not in {"SCALP", "SWING"}:
        # Preserve the lane selected by the legacy result when it is explicit.
        if legacy.get("scalp_signal") == "BUY":
            mode = "SCALP"
        elif legacy.get("swing_signal") == "BUY":
            mode = "SWING"
        else:
            mode = "SCALP"

    if bearish_weak_recovery:
        five_bias = "RECOVERY"
    else:
        five_bias = _bias(mtf, "5m")

    setup_type = "REVERSAL" if confirmed_reversal else ("CONTINUATION" if continuation_break and pullback_holds else None)

    return {
        "trade_mode": mode,
        "setup_type": setup_type,
        "market": {
            "5m_bias": five_bias,
            "15m_bias": _bias(mtf, "15m"),
            "1h_bias": _bias(mtf, "1h"),
            "4h_bias": _bias(mtf, "4h"),
            "btc_guard": facts.btc_guard,
        },
        "structure": {
            "location_at_support": support,
            "location_pullback": pullback,
            "selling_pressure_weakening": _has_pattern(multi, "5C_SELLING_PRESSURE_WEAKENING"),
            "higher_low": higher_low,
            "reclaim": reclaim,
            "continuation_break": continuation_break,
            "pullback_holds": pullback_holds,
            "new_structure_after_prior_stop": facts.new_structure_after_prior_stop,
            "multi_candle_bias": multi.get("bias"),
            "multi_candle_strength": multi.get("strength", 0),
            "multi_candle_patterns": tuple(multi.get("patterns", [])),
        },
        "trigger": {
            "confirmed_reversal": confirmed_reversal,
            "bullish_pattern": next((x for x in legacy.get("scalp_reasons", []) if "BULLISH" in str(x)), None),
            "rsi_recovering": bool(legacy.get("scalp_recovery_confirmation")),
            "volume_ratio_5m": float(legacy.get("volume_ratio_5m", legacy.get("scalp_min_volume_ratio", 0.0)) or 0.0),
        },
        "execution": {
            "closed_candle": bool(c5 and c15),
            "spread_percent": facts.spread_percent,
        },
        "risk": {
            "stop_distance_percent": facts.stop_distance_percent,
            "reward_risk": facts.reward_risk,
        },
        "metadata": {
            "legacy_score": legacy.get("score"),
            "legacy_scalp_score": legacy.get("scalp_score"),
            "legacy_swing_score": legacy.get("swing_score"),
            "legacy_recovery_confirmation": legacy.get("scalp_recovery_confirmation"),
            "legacy_confirmed_reversal": legacy.get("scalp_confirmed_reversal"),
            "legacy_mtf_bias": legacy.get("mtf_bias"),
            "legacy_mtf_timeframe_bias": legacy.get("mtf_timeframe_bias", {}),
            "multi_candle_context": multi,
            "prior_exit": facts.prior_exit,
            "prior_context_fingerprint_same": facts.prior_context_fingerprint_same,
        },
    }


def evaluate_legacy_with_entry_v2(facts: EntryV2MarketFacts) -> EntryDecision:
    """Evaluate the legacy observation through the isolated Entry v2 contract."""
    return EntryEngineV2().evaluate(build_entry_scenario(facts))
