from __future__ import annotations

from multi_candle_context import analyze_multi_candle_context


def candle(o, h, l, c, v=100.0):
    return {"open": o, "high": h, "low": l, "close": c, "volume": v}


def test_requires_eight_closed_candles():
    result = analyze_multi_candle_context([candle(10, 11, 9, 10.5)] * 7)
    assert result["available"] is False
    assert result["bias"] == "UNKNOWN"


def test_detects_five_candle_bearish_momentum():
    candles = [
        candle(100, 101, 98, 99),
        candle(99, 100, 96, 97),
        candle(97, 98, 94, 95),
        candle(95, 96, 92, 93),
        candle(93, 94, 90, 91),
        candle(91, 92, 89, 90),
        candle(90, 91, 88, 89),
        candle(89, 90, 87, 88),
    ]
    result = analyze_multi_candle_context(candles)
    assert "5C_BEARISH_MOMENTUM" in result["patterns"]
    assert result["bearish_warning"] is True
    assert result["bias"] == "BEARISH"


def test_detects_selloff_to_recovery_without_using_newest_forming_candle():
    candles = [
        candle(100, 101, 97, 98),
        candle(98, 99, 94, 95),
        candle(95, 96, 91, 92),
        candle(92, 93, 89, 90),
        candle(90, 92, 89, 91),
        candle(91, 94, 90, 93),
        candle(93, 96, 92, 95),
        candle(95, 98, 94, 97),
    ]
    result = analyze_multi_candle_context(candles)
    assert "8C_SELL_OFF_TO_RECOVERY" in result["patterns"]
    assert "LARGER_SELL_OFF_IS_RECOVERING" in result["reasons"]
    assert result["bias"] == "BULLISH"


def test_three_bearish_crows_are_flagged():
    candles = [
        candle(100, 101, 99, 100.5),
        candle(100.5, 101, 99.5, 100),
        candle(100, 100.5, 98, 98.5),
        candle(98.5, 99, 96, 96.8),
        candle(96.8, 97.2, 94, 94.7),
        candle(94.7, 95, 92, 92.8),
        candle(92.8, 93, 90, 90.9),
        candle(90.9, 91.2, 88, 89.2),
    ]
    result = analyze_multi_candle_context(candles)
    assert "THREE_BEARISH_CROWS" in result["patterns"]
    assert result["bearish_warning"] is True


def test_does_not_claim_entry_or_change_existing_score():
    candles = [candle(100 + i, 102 + i, 99 + i, 101 + i) for i in range(8)]
    result = analyze_multi_candle_context(candles)
    assert "score" not in result
    assert "signal" not in result
    assert result["window_3"] == 3
    assert result["window_5"] == 5
    assert result["window_7"] == 7
    assert result["window_8"] == 8
