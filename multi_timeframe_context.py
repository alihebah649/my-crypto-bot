"""Multi-timeframe closed-candle context for entry quality.

The module deliberately does not create a standalone BUY signal. It compares
3/5/7/8-candle structures on 5m, 15m, 1h and 4h, with higher timeframes used as
context and 5m remaining the execution trigger.

Callers must pass CLOSED candles. The live/forming candle is removed by the
strategy layer before this module is called, so this module never double-skips
the newest closed candle.
"""
from __future__ import annotations

from typing import Dict, Iterable, Mapping

from multi_candle_context import analyze_multi_candle_context

TIMEFRAME_WEIGHTS = {"5m": 1, "15m": 2, "1h": 3, "4h": 4}


def _strength(context: Mapping[str, object]) -> int:
    return int(context.get("strength", 0) or 0)


def _bias(context: Mapping[str, object]) -> str:
    return str(context.get("bias", "UNKNOWN")).upper()


def analyze_multi_timeframe_context(
    candles_by_timeframe: Mapping[str, Iterable[dict]],
) -> Dict[str, object]:
    """Compare closed-candle structures across 5m/15m/1h/4h."""
    frames: Dict[str, dict] = {}
    weighted_bull = 0
    weighted_bear = 0
    available_weight = 0

    for timeframe in TIMEFRAME_WEIGHTS:
        candles = list(candles_by_timeframe.get(timeframe, []) or [])
        context = analyze_multi_candle_context(candles)
        frames[timeframe] = context
        if not context.get("available"):
            continue
        weight = TIMEFRAME_WEIGHTS[timeframe]
        available_weight += weight
        strength = _strength(context)
        if _bias(context) == "BULLISH":
            weighted_bull += strength * weight
        elif _bias(context) == "BEARISH":
            weighted_bear += strength * weight

    net = weighted_bull - weighted_bear
    if net >= 6:
        bias = "BULLISH"
    elif net <= -6:
        bias = "BEARISH"
    else:
        bias = "NEUTRAL"

    h1 = frames["1h"]
    h4 = frames["4h"]
    m15 = frames["15m"]
    m5 = frames["5m"]

    higher_bearish = (
        _bias(h1) == "BEARISH" and _strength(h1) >= 3
        and _bias(h4) == "BEARISH" and _strength(h4) >= 3
    )
    higher_bullish = (
        _bias(h1) == "BULLISH" and _strength(h1) >= 3
        and _bias(h4) == "BULLISH" and _strength(h4) >= 3
    )
    # A weak 5m recovery against a bearish 15m/1h/4h stack is the classic
    # falling-knife/temporary-bounce setup. A confirmed 5m breakout is allowed
    # through because it is the actual execution trigger.
    weak_countertrend_recovery = (
        higher_bearish
        and _bias(m15) == "BEARISH"
        and _bias(m5) != "BULLISH"
    )
    aligned_bullish = (
        higher_bullish
        and _bias(m15) in {"BULLISH", "NEUTRAL"}
        and _bias(m5) in {"BULLISH", "NEUTRAL"}
    )

    return {
        "available": available_weight > 0,
        "bias": bias,
        "weighted_bull": weighted_bull,
        "weighted_bear": weighted_bear,
        "net": net,
        "available_weight": available_weight,
        "frames": frames,
        "higher_timeframes_bearish": higher_bearish,
        "higher_timeframes_bullish": higher_bullish,
        "weak_countertrend_recovery": weak_countertrend_recovery,
        "aligned_bullish": aligned_bullish,
        "timeframes": ["5m", "15m", "1h", "4h"],
    }
