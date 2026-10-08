from __future__ import annotations

import dual_mode_strategy


def candle(open_price: float, high: float, low: float, close: float, volume: float = 100.0) -> dict:
    return {"open": open_price, "high": high, "low": low, "close": close, "volume": volume}


def candles(count: int) -> list[dict]:
    return [candle(100.0, 101.0, 99.0, 100.0, 100.0) for _ in range(count)]


def _run(monkeypatch, pattern_result, mtf_frames=None):
    monkeypatch.setattr(dual_mode_strategy, "calculate_rsi", lambda prices, period=14: 44.0)
    monkeypatch.setattr(
        dual_mode_strategy,
        "calculate_bollinger",
        lambda data, period=20, deviations=2.0: (
            (100.0, 110.0, 121.0) if len(data) >= 100 else (99.5, 110.0, 121.0)
        ),
    )
    monkeypatch.setattr(dual_mode_strategy, "_volume_ratio", lambda data, window=20: 1.20)
    monkeypatch.setattr(dual_mode_strategy, "bullish_pattern", lambda data: pattern_result)
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
            "bias": "NEUTRAL",
            "net": 0,
            "weighted_bull": 0,
            "weighted_bear": 0,
            "weak_countertrend_recovery": False,
            "aligned_bullish": False,
            "higher_timeframes_bearish": False,
            "higher_timeframes_bullish": False,
            "frames": mtf_frames or {},
        },
    )

    return dual_mode_strategy.score_symbol(
        "FETUSDT",
        {"lastPrice": "100.0"},
        candles(130),
        candles(30),
    )


def test_confirmed_bullish_candlestick_pushes_strong_confluence_to_scalp_buy(monkeypatch):
    result = _run(monkeypatch, (True, "BULLISH_ENGULFING", True))

    # Correlated support/RSI/Bollinger evidence is capped, pattern points are
    # capped, and structure is mandatory before a SCALP entry.
    assert result["scalp_score"] == 61
    assert result["scalp_gate"] is False
    assert result["scalp_signal"] == "HOLD"
    assert result["trade_mode"] == "NONE"


def test_unconfirmed_bullish_candlestick_plus_recovery_can_cross_scalp_threshold(monkeypatch):
    result = _run(monkeypatch, (True, "MORNING_STAR", False))

    # Unconfirmed pattern evidence cannot authorize the trade without
    # independent structural confirmation.
    assert result["scalp_score"] == 49
    assert result["scalp_gate"] is False
    assert result["scalp_signal"] == "HOLD"
    assert result["trade_mode"] == "NONE"


def test_seller_failure_confirmation_is_exposed_from_existing_5m_or_15m_context(monkeypatch):
    result_5m = _run(
        monkeypatch,
        (False, "NEUTRAL", False),
        {
            "5m": {"patterns": ["5C_SELLING_PRESSURE_WEAKENING"]},
            "15m": {"patterns": []},
        },
    )
    assert result_5m["seller_failure_confirmed"] is True

    result_15m = _run(
        monkeypatch,
        (False, "NEUTRAL", False),
        {
            "5m": {"patterns": []},
            "15m": {"patterns": ["8C_SELL_OFF_TO_RECOVERY"]},
        },
    )
    assert result_15m["seller_failure_confirmed"] is True

    result_none = _run(
        monkeypatch,
        (False, "NEUTRAL", False),
        {
            "5m": {"patterns": ["7C_HIGHER_LOW_STRUCTURE"]},
            "15m": {"patterns": ["7C_LOWER_HIGH_STRUCTURE"]},
        },
    )
    assert result_none["seller_failure_confirmed"] is False
