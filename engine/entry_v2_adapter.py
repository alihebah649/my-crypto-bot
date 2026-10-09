"""Legacy -> Entry v2 adapter.

This module is a translation boundary only: it does not alter the legacy
strategy and it does not execute trades. It converts the legacy result plus
closed candles into explicit Entry v2 market facts.

The important distinction is preserved:
- 5m supplies the execution trigger;
- 15m supplies setup/location context;
- 1h and 4h supply higher-timeframe context;
- 3/5/7/8-candle analysis is retained for each timeframe;
- a legacy recovery flag never becomes a structural reversal by itself.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from multi_candle_context import analyze_multi_candle_context
from multi_timeframe_context import analyze_multi_timeframe_context
from .entry_engine import EntryDecision, EntryEngineV2
from .stop_structure import calculate_structural_stop_candidate

TIMEFRAMES = ("5m", "15m", "1h", "4h")


@dataclass(frozen=True)
class EntryV2MarketFacts:
    """Inputs required to translate one legacy strategy observation."""
    legacy_result: Mapping[str, Any]
    candles_5m: Sequence[Mapping[str, Any]]
    candles_15m: Sequence[Mapping[str, Any]]
    candles_1h: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    candles_4h: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    stop_distance_percent: float = 0.0
    reward_risk: float | None = None
    spread_percent: float = 0.0
    target_price: float | None = None
    target_source: str | None = None
    target_status: str | None = None
    prior_exit: str | None = None
    prior_context_fingerprint_same: bool = False
    new_structure_after_prior_stop: bool = False
    btc_guard: str = "PASS"


def _closed(candles: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Drop the currently forming candle, matching the legacy convention."""
    return list(candles[:-1]) if len(candles) > 1 else []


def _recovery_follow_through_shadow(
    candles_5m: Sequence[Mapping[str, Any]],
    *,
    trade_mode: str,
    recovery_candidate: bool,
    bearish_context: bool,
) -> dict[str, Any]:
    """Counterfactual only: evaluate two closed 5m bars of recovery follow-through."""
    closed = _closed(candles_5m)
    if len(closed) < 2:
        return {
            "schema_version": 1,
            "shadow_only": True,
            "applicable": trade_mode == "SCALP" and recovery_candidate and bearish_context,
            "available": False,
            "follow_through_confirmed": None,
            "would_be_action": "INSUFFICIENT_DATA",
            "reason": "TWO_CLOSED_5M_CANDLES_REQUIRED",
            "closed_candles_used": len(closed),
        }

    first, second = closed[-2], closed[-1]
    try:
        first_open, first_high = float(first["open"]), float(first["high"])
        first_low, first_close = float(first["low"]), float(first["close"])
        second_open, second_low, second_close = (
            float(second["open"]), float(second["low"]), float(second["close"])
        )
    except (KeyError, TypeError, ValueError):
        return {
            "schema_version": 1,
            "shadow_only": True,
            "applicable": trade_mode == "SCALP" and recovery_candidate and bearish_context,
            "available": False,
            "follow_through_confirmed": None,
            "would_be_action": "INSUFFICIENT_DATA",
            "reason": "INVALID_CLOSED_CANDLE_FIELDS",
            "closed_candles_used": len(closed),
        }

    first_bullish = first_close > first_open
    second_bullish = second_close > second_open
    second_close_above_first_high = second_close > first_high
    second_low_above_first_low = second_low > first_low
    confirmed = bool(first_bullish and second_bullish and second_close_above_first_high)
    applicable = bool(trade_mode == "SCALP" and recovery_candidate and bearish_context)
    action = (
        "NOT_APPLICABLE" if not applicable
        else "WOULD_ALLOW" if confirmed
        else "WOULD_BLOCK"
    )
    return {
        "schema_version": 1,
        "shadow_only": True,
        "applicable": applicable,
        "available": True,
        "trade_mode": trade_mode,
        "bearish_context": bool(bearish_context),
        "recovery_candidate": bool(recovery_candidate),
        "first_closed_candle_bullish": first_bullish,
        "second_closed_candle_bullish": second_bullish,
        "second_close_above_first_high": second_close_above_first_high,
        "second_low_above_first_low": second_low_above_first_low,
        "follow_through_confirmed": confirmed,
        "would_be_action": action,
        "reason": (
            "TWO_CLOSED_BULLISH_BARS_AND_SECOND_CLOSE_BREAKS_FIRST_HIGH"
            if confirmed else "TWO_CANDLE_FOLLOW_THROUGH_NOT_CONFIRMED"
        ),
        "closed_candles_used": 2,
    }


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
        "BOLLINGER_LOWER_SUPPORT", "BOLLINGER_NEAR_SUPPORT",
        "BOLLINGER_LOWER_HALF", "MACRO_SUPPORT",
    ))
    pullback = any(token in reasons for token in ("PULLBACK", "EMA100_TREND")) and not support
    return support, pullback


def build_entry_scenario(facts: EntryV2MarketFacts) -> dict[str, Any]:
    legacy = facts.legacy_result
    candles_by_timeframe = {
        "5m": _closed(facts.candles_5m),
        "15m": _closed(facts.candles_15m),
        "1h": _closed(facts.candles_1h),
        "4h": _closed(facts.candles_4h),
    }

    mtf = analyze_multi_timeframe_context(candles_by_timeframe)
    candle_contexts = {
        timeframe: analyze_multi_candle_context(candles_by_timeframe[timeframe])
        for timeframe in TIMEFRAMES
    }
    multi5 = candle_contexts["5m"]
    multi15 = candle_contexts["15m"]
    support, pullback = _location_from_legacy(legacy)
    confirmed_reversal = bool(legacy.get("scalp_confirmed_reversal"))

    continuation_break = bool(
        _has_pattern(multi5, "THREE_BULLISH_ADVANCE", "THREE_BULLISH_SOLDIERS", "5C_BULLISH_MOMENTUM")
        and _bias(mtf, "5m") == "BULLISH"
    )
    pullback_holds = bool(
        _has_pattern(multi5, "7C_HIGHER_LOW_STRUCTURE", "8C_SELL_OFF_TO_RECOVERY")
        or _has_pattern(candle_contexts["15m"], "7C_HIGHER_LOW_STRUCTURE", "8C_SELL_OFF_TO_RECOVERY")
    )
    # Higher-low is structural confirmation, not a 5m-only property. A
    # confirmed 15m higher-low is sufficient to validate the setup context
    # for a 5m reversal trigger. This prevents a valid 5m/15m reversal from
    # being falsely rejected just because the 5m window has not printed its
    # own higher-low yet (RENDER-style false negative observed in Paper).
    higher_low = bool(
        _has_pattern(multi5, "7C_HIGHER_LOW_STRUCTURE")
        or _has_pattern(multi15, "7C_HIGHER_LOW_STRUCTURE")
    )
    reclaim = bool(
        confirmed_reversal
        and (
            _has_pattern(multi5, "8C_SELL_OFF_TO_RECOVERY", "THREE_BULLISH_ADVANCE", "FOUR_C_BEAR_TO_BULL_REVERSAL")
            or _has_pattern(candle_contexts["15m"], "7C_HIGHER_LOW_STRUCTURE", "THREE_BULLISH_ADVANCE", "FOUR_C_BEAR_TO_BULL_REVERSAL")
        )
    )

    if not confirmed_reversal:
        higher_low = False
        reclaim = False

    bearish_weak_recovery = bool(
        all(_bias(mtf, tf) == "BEARISH" for tf in ("15m", "1h", "4h"))
        and not confirmed_reversal
    )

    mode = str(legacy.get("trade_mode", "NONE")).upper()
    if mode not in {"SCALP", "SWING"}:
        if legacy.get("scalp_signal") == "BUY":
            mode = "SCALP"
        elif legacy.get("swing_signal") == "BUY":
            mode = "SWING"
        else:
            mode = "SCALP"

    five_bias = "RECOVERY" if bearish_weak_recovery else _bias(mtf, "5m")
    setup_type = "REVERSAL" if confirmed_reversal else (
        "CONTINUATION" if continuation_break and pullback_holds else None
    )

    seller_failure = bool(
        _has_pattern(
            multi5,
            "5C_SELLING_PRESSURE_WEAKENING",
            "FOUR_C_BEAR_TO_BULL_REVERSAL",
            "8C_SELL_OFF_TO_RECOVERY",
        )
        or _has_pattern(
            candle_contexts["15m"],
            "5C_SELLING_PRESSURE_WEAKENING",
            "FOUR_C_BEAR_TO_BULL_REVERSAL",
            "8C_SELL_OFF_TO_RECOVERY",
        )
    )

    entry_price = float(legacy.get("price", 0.0) or 0.0)
    # The structural-stop helper owns the "drop the currently forming candle"
    # rule. Pass the raw candle windows here; otherwise Entry v2 would drop the
    # last candle twice and weaken the diagnostic candidate.
    raw_candles_by_timeframe = {
        "5m": facts.candles_5m,
        "15m": facts.candles_15m,
        "1h": facts.candles_1h,
        "4h": facts.candles_4h,
    }
    structural_stop = calculate_structural_stop_candidate(
        trade_mode=mode,
        entry_price=entry_price,
        candles_by_timeframe=raw_candles_by_timeframe,
    )
    atr15 = float(legacy.get("atr", 0.0) or 0.0)
    atr_stop = entry_price - (2.0 * atr15) if entry_price > 0.0 and atr15 > 0.0 else None
    structural_distance_percent = (
        (entry_price - structural_stop.price) / entry_price * 100.0
        if entry_price > 0.0 and structural_stop.price is not None else None
    )
    # None means the comparison is unavailable; false is reserved for a
    # valid structural candidate that would not widen the current ATR stop.
    structural_would_widen = (
        None
        if atr_stop is None or structural_stop.price is None
        else bool(structural_stop.price < atr_stop)
    )

    try:
        mtf_net_for_recovery = float(legacy.get("mtf_net", 0.0) or 0.0)
    except (TypeError, ValueError):
        mtf_net_for_recovery = 0.0
    bearish_recovery_context = bool(
        legacy.get("mtf_higher_timeframes_bearish")
        or all(_bias(mtf, tf) == "BEARISH" for tf in ("15m", "1h", "4h"))
        or _bias(mtf, "15m") == "BEARISH"
        or mtf_net_for_recovery <= -20.0
    )
    recovery_follow_through = _recovery_follow_through_shadow(
        facts.candles_5m,
        trade_mode=mode,
        recovery_candidate=bool(
            legacy.get("scalp_recovery_confirmation") or confirmed_reversal
        ),
        bearish_context=bearish_recovery_context,
    )

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
            "selling_pressure_weakening": seller_failure,
            "higher_low": higher_low,
            "reclaim": reclaim,
            "continuation_break": continuation_break,
            "pullback_holds": pullback_holds,
            "higher_low_timeframes": tuple(
                timeframe
                for timeframe, context in (("5m", multi5), ("15m", multi15))
                if _has_pattern(context, "7C_HIGHER_LOW_STRUCTURE")
            ),
            "new_structure_after_prior_stop": facts.new_structure_after_prior_stop,
            "multi_candle_bias": multi5.get("bias"),
            "multi_candle_strength": multi5.get("strength", 0),
            "multi_candle_patterns": tuple(multi5.get("patterns", [])),
            "multi_candle_by_timeframe": {
                tf: {
                    "bias": ctx.get("bias"),
                    "strength": ctx.get("strength", 0),
                    "bull_score": ctx.get("bull_score", 0),
                    "bear_score": ctx.get("bear_score", 0),
                    "patterns": tuple(ctx.get("patterns", [])),
                    "bearish_warning": bool(ctx.get("bearish_warning")),
                }
                for tf, ctx in candle_contexts.items()
            },
        },
        "trigger": {
            "confirmed_reversal": confirmed_reversal,
            "bullish_pattern": next(
                (x for x in legacy.get("scalp_reasons", []) if "BULLISH" in str(x)),
                None,
            ),
            "rsi_recovering": bool(legacy.get("scalp_recovery_confirmation")),
            "volume_ratio_5m": float(
                legacy.get("volume_ratio_5m", legacy.get("scalp_min_volume_ratio", 0.0)) or 0.0
            ),
            "recovery_follow_through_shadow": recovery_follow_through,
        },
        "execution": {
            "closed_candle": bool(candles_by_timeframe["5m"] and candles_by_timeframe["15m"]),
            "spread_percent": facts.spread_percent,
        },
        "risk": {
            "stop_distance_percent": facts.stop_distance_percent,
            "atr_stop_loss": atr_stop,
            "structural_stop_candidate": structural_stop.price,
            "structural_stop_source": structural_stop.source,
            "structural_stop_timeframe": structural_stop.timeframe,
            "structural_stop_candle_index": structural_stop.candle_index,
            "structural_stop_distance_percent": structural_distance_percent,
            "structural_stop_would_widen_current_model": structural_would_widen,
            "reward_risk": facts.reward_risk,
            "target_price": facts.target_price,
            "target_source": facts.target_source,
            "target_status": facts.target_status,
        },
        "metadata": {
            "legacy_score": legacy.get("score"),
            "legacy_scalp_score": legacy.get("scalp_score"),
            "legacy_swing_score": legacy.get("swing_score"),
            "legacy_recovery_confirmation": legacy.get("scalp_recovery_confirmation"),
            "legacy_confirmed_reversal": legacy.get("scalp_confirmed_reversal"),
            "legacy_mtf_bias": legacy.get("mtf_bias"),
            "legacy_mtf_timeframe_bias": legacy.get("mtf_timeframe_bias", {}),
            "multi_candle_context": multi5,
            "multi_candle_context_by_timeframe": candle_contexts,
            "mtf_context": mtf,
            "prior_exit": facts.prior_exit,
            "prior_context_fingerprint_same": facts.prior_context_fingerprint_same,
        },
    }


def evaluate_legacy_with_entry_v2(facts: EntryV2MarketFacts) -> EntryDecision:
    """Evaluate the legacy observation through the isolated Entry v2 contract."""
    return EntryEngineV2().evaluate(build_entry_scenario(facts))
