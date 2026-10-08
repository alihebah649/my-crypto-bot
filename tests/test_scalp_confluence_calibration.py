from __future__ import annotations

import dual_mode_strategy


def candle(open_price: float, high: float, low: float, close: float, volume: float = 100.0) -> dict:
    return {"open": open_price, "high": high, "low": low, "close": close, "volume": volume}


def candles(count: int) -> list[dict]:
    return [candle(100.0, 101.0, 99.0, 100.0, 100.0) for _ in range(count)]


def _run(monkeypatch, mtf_bias: str):
    monkeypatch.setattr(dual_mode_strategy, "calculate_rsi", lambda prices, period=14: 44.0)
    monkeypatch.setattr(
        dual_mode_strategy,
        "calculate_bollinger",
        lambda data, period=20, deviations=2.0: (
            (100.0, 110.0, 121.0) if len(data) >= 100 else (99.5, 110.0, 121.0)
        ),
    )
    monkeypatch.setattr(dual_mode_strategy, "_volume_ratio", lambda data, window=20: 1.20)
    monkeypatch.setattr(dual_mode_strategy, "bullish_pattern", lambda data: (False, "NEUTRAL", False))
    monkeypatch.setattr(
        dual_mode_strategy,
        "_scalp_recovery_confirmation",
        lambda data, current_rsi: (True, 2, ["5M_PRICE_RECOVERY", "5M_BULLISH_BODY"]),
    )
    monkeypatch.setattr(
        dual_mode_strategy,
        "analyze_multi_timeframe_context",
        lambda data: {
            "available": True,
            "bias": mtf_bias,
            "net": 1 if mtf_bias == "BULLISH" else 0,
            "weighted_bull": 1 if mtf_bias == "BULLISH" else 0,
            "weighted_bear": 0,
            "weak_countertrend_recovery": False,
            "aligned_bullish": mtf_bias == "BULLISH",
            "higher_timeframes_bearish": False,
            "higher_timeframes_bullish": mtf_bias == "BULLISH",
            "frames": {},
        },
    )

    return dual_mode_strategy.score_symbol(
        "FETUSDT",
        {"lastPrice": "100.0"},
        candles(130),
        candles(30),
    )


def test_strong_scalp_confluence_without_candlestick_stops_at_60(monkeypatch):
    result = _run(monkeypatch, "NEUTRAL")

    # The reversion family is capped and structural confirmation is mandatory.
    assert result["scalp_score"] == 41
    assert result["scalp_gate"] is False
    assert "SCALP_STRUCTURE_NOT_CONFIRMED" in result["scalp_gate_reasons"]
    assert result["scalp_signal"] == "HOLD"
    assert result["trade_mode"] == "NONE"


def test_adding_bullish_mtf_still_stops_below_scalp_threshold(monkeypatch):
    result = _run(monkeypatch, "BULLISH")

    # Bullish MTF context can raise the diagnostic score, but cannot substitute
    # for local structural confirmation.
    assert result["scalp_score"] == 45
    assert result["scalp_gate"] is False
    assert "SCALP_STRUCTURE_NOT_CONFIRMED" in result["scalp_gate_reasons"]
    assert result["scalp_signal"] == "HOLD"
    assert result["trade_mode"] == "NONE"
