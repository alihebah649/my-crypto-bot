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
    higher_low = _has_pattern(multi5, "7C_HIGHER_LOW_STRUCTURE")
    reclaim = bool(
        confirmed_reversal
        and (
            _has_pattern(multi5, "8C_SELL_OFF_TO_RECOVERY", "THREE_BULLISH_ADVANCE", "FOUR_C_BEAR_TO_BULL_REVERSAL")
            or _has_pattern(candle_contexts["15m"], "7C_HIGHER_LOW_STRUCTURE", "THREE_BULLISH_ADVANCE", "FOUR_C_BEAR_TO_BULL_REVERSAL")
        )
    )

    # Recovery alone cannot manufacture structural reversal.
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
        },
        "execution": {
            "closed_candle": bool(candles_by_timeframe["5m"] and candles_by_timeframe["15m"]),
            "spread_percent": facts.spread_percent,
        },
        "risk": {
            "stop_distance_percent": facts.stop_distance_percent,
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
