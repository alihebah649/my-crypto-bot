"""Multi-candle price-action context for the dual-lane strategy.

Closed-candle-only structural analysis across 3/4/5/7/8-candle windows.
The module is descriptive: it reports market structure and warnings but does
not directly authorize a trade.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

Candle = Dict[str, float]


def _body(c: Candle) -> float:
    return abs(float(c["close"]) - float(c["open"]))


def _bull(c: Candle) -> bool:
    return float(c["close"]) > float(c["open"])


def _bear(c: Candle) -> bool:
    return float(c["close"]) < float(c["open"])


def _upper_wick(c: Candle) -> float:
    return float(c["high"]) - max(float(c["open"]), float(c["close"]))


def _lower_wick(c: Candle) -> float:
    return min(float(c["open"]), float(c["close"])) - float(c["low"])


def _consecutive_direction(candles: List[Candle]) -> Tuple[int, int]:
    bulls = bears = 0
    for c in reversed(candles):
        if _bull(c):
            if bears:
                break
            bulls += 1
        elif _bear(c):
            if bulls:
                break
            bears += 1
        else:
            break
    return bulls, bears


def analyze_multi_candle_context(candles: List[Candle]) -> Dict[str, object]:
    """Analyze 3/4/5/7/8 closed-candle structure without issuing a BUY signal."""
    if len(candles) < 8:
        return {
            "available": False,
            "bias": "UNKNOWN",
            "strength": 0,
            "patterns": [],
            "reasons": ["INSUFFICIENT_8_CLOSED_CANDLES"],
            "bearish_warning": False,
        }

    c3 = candles[-3:]
    c4 = candles[-4:]
    c5 = candles[-5:]
    c7 = candles[-7:]
    c8 = candles[-8:]
    patterns: List[str] = []
    reasons: List[str] = []
    bull_score = 0
    bear_score = 0

    # 3-candle directional structure and classic advance/decline shapes.
    a, b, c = c3
    if _bull(a) and _bull(b) and _bull(c) and float(a["close"]) > float(b["close"]) > float(c["close"]):
        patterns.append("THREE_BULLISH_ADVANCE")
        bull_score += 2
    if _bear(a) and _bear(b) and _bear(c) and float(a["close"]) < float(b["close"]) < float(c["close"]):
        patterns.append("THREE_BEARISH_DECLINE")
        bear_score += 2

    if all(_bull(x) for x in c3) and all(_lower_wick(x) <= _body(x) * 0.6 for x in c3):
        if float(c3[1]["close"]) > float(c3[0]["close"]) and float(c3[2]["close"]) > float(c3[1]["close"]):
            patterns.append("THREE_BULLISH_SOLDIERS")
            bull_score += 3
    if all(_bear(x) for x in c3) and all(_upper_wick(x) <= _body(x) * 0.6 for x in c3):
        if float(c3[1]["close"]) < float(c3[0]["close"]) and float(c3[2]["close"]) < float(c3[1]["close"]):
            patterns.append("THREE_BEARISH_CROWS")
            bear_score += 3

    # 4-candle sequence: two-candle confirmation after a directional pair.
    bull4 = sum(_bull(x) for x in c4)
    bear4 = sum(_bear(x) for x in c4)
    if bull4 >= 3 and float(c4[-1]["close"]) > float(c4[0]["open"]):
        patterns.append("FOUR_BULLISH_SEQUENCE")
        bull_score += 2
    if bear4 >= 3 and float(c4[-1]["close"]) < float(c4[0]["open"]):
        patterns.append("FOUR_BEARISH_SEQUENCE")
        bear_score += 2

    # 4-candle reversal confirmation: an initial selloff, stabilization, then
    # two bullish closes that reclaim the prior midpoint.
    midpoint_first = (float(c4[0]["open"]) + float(c4[0]["close"])) / 2.0
    if _bear(c4[0]) and _bear(c4[1]) and _bull(c4[2]) and _bull(c4[3]) and float(c4[3]["close"]) > midpoint_first:
        patterns.append("FOUR_C_BEAR_TO_BULL_REVERSAL")
        bull_score += 3
    if _bull(c4[0]) and _bull(c4[1]) and _bear(c4[2]) and _bear(c4[3]) and float(c4[3]["close"]) < midpoint_first:
        patterns.append("FOUR_C_BULL_TO_BEAR_REVERSAL")
        bear_score += 3

    # 5-candle momentum and pressure exhaustion.
    bulls5 = sum(_bull(x) for x in c5)
    bears5 = sum(_bear(x) for x in c5)
    if bulls5 >= 4 and float(c5[-1]["close"]) > float(c5[0]["close"]):
        patterns.append("5C_BULLISH_MOMENTUM")
        bull_score += 2
    if bears5 >= 4 and float(c5[-1]["close"]) < float(c5[0]["close"]):
        patterns.append("5C_BEARISH_MOMENTUM")
        bear_score += 2

    bodies5 = [_body(x) for x in c5]
    if bears5 >= 3 and bodies5[-1] < bodies5[-2] < bodies5[-3]:
        patterns.append("5C_SELLING_PRESSURE_WEAKENING")
        bull_score += 2
        reasons.append("SELLING_PRESSURE_WEAKENING")
    if bulls5 >= 3 and bodies5[-1] < bodies5[-2] < bodies5[-3]:
        patterns.append("5C_BUYING_PRESSURE_WEAKENING")
        bear_score += 1
        reasons.append("BUYING_PRESSURE_WEAKENING")

    # 7/8-candle broader structure.
    older = c8[:4]
    recent = c8[4:]
    older_change = float(older[-1]["close"]) - float(older[0]["open"])
    recent_change = float(recent[-1]["close"]) - float(recent[0]["open"])
    if older_change < 0 and recent_change > 0:
        patterns.append("8C_SELL_OFF_TO_RECOVERY")
        bull_score += 3
        reasons.append("LARGER_SELL_OFF_IS_RECOVERING")
    elif older_change > 0 and recent_change < 0:
        patterns.append("8C_RALLY_TO_PULLBACK")
        bear_score += 2
        reasons.append("LARGER_RALLY_IS_PULLING_BACK")

    lows = [float(x["low"]) for x in c7]
    highs = [float(x["high"]) for x in c7]
    if lows[-1] > min(lows[:3]) and lows[-2] >= min(lows[:3]):
        patterns.append("7C_HIGHER_LOW_STRUCTURE")
        bull_score += 2
    if highs[-1] < max(highs[:3]) and highs[-2] <= max(highs[:3]):
        patterns.append("7C_LOWER_HIGH_STRUCTURE")
        bear_score += 2

    bulls_end, bears_end = _consecutive_direction(c5)
    if bears_end >= 3:
        bear_score += 1
        reasons.append("CONSECUTIVE_BEARISH_CANDLES")
    if bulls_end >= 3:
        bull_score += 1
        reasons.append("CONSECUTIVE_BULLISH_CANDLES")

    strength = abs(bull_score - bear_score)
    if bull_score >= bear_score + 3:
        bias = "BULLISH"
    elif bear_score >= bull_score + 3:
        bias = "BEARISH"
    else:
        bias = "NEUTRAL"

    bearish_warning = bool(
        bear_score >= bull_score + 3
        and (
            "5C_BEARISH_MOMENTUM" in patterns
            or "THREE_BEARISH_CROWS" in patterns
            or "FOUR_BEARISH_SEQUENCE" in patterns
            or bears_end >= 3
        )
    )

    if bias == "BULLISH":
        reasons.append("MULTI_CANDLE_BULLISH_CONTEXT")
    elif bias == "BEARISH":
        reasons.append("MULTI_CANDLE_BEARISH_CONTEXT")
    else:
        reasons.append("MULTI_CANDLE_MIXED_CONTEXT")

    return {
        "available": True,
        "bias": bias,
        "strength": strength,
        "bull_score": bull_score,
        "bear_score": bear_score,
        "patterns": patterns,
        "reasons": reasons,
        "bearish_warning": bearish_warning,
        "window_3": 3,
        "window_4": 4,
        "window_5": 5,
        "window_7": 7,
        "window_8": 8,
    }
