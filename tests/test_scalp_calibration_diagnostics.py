from __future__ import annotations

import dual_mode_strategy


def candle(open_price: float, high: float, low: float, close: float, volume: float = 100.0) -> dict:
    return {"open": open_price, "high": high, "low": low, "close": close, "volume": volume}


def candles(count: int = 30) -> list[dict]:
    return [candle(100.0, 101.0, 99.0, 100.0, 100.0) for _ in range(count)]


def test_fet_like_recovery_is_gate_true_but_below_scalp_threshold(monkeypatch):
    """Lock the observed calibration gap without changing production scoring."""
    monkeypatch.setattr(
        dual_mode_strategy,
        "calculate_rsi",
        lambda prices, period=14: 48.66,
    )
    monkeypatch.setattr(
        dual_mode_strategy,
        "calculate_bollinger",
        lambda candles, period=20, deviations=2.0: (
            (95.0, 110.0, 121.0) if len(candles) >= 100 else (99.5, 110.0, 121.0)
        ),
    )
    monkeypatch.setattr(dual_mode_strategy, "_volume_ratio", lambda candles, window=20: 1.127)
    monkeypatch.setattr(dual_mode_strategy, "bullish_pattern", lambda candles: (False, "NEUTRAL", False))
    monkeypatch.setattr(
        dual_mode_strategy,
        "_scalp_recovery_confirmation",
        lambda candles, current_rsi: (True, 2, ["5M_PRICE_RECOVERY", "5M_BULLISH_BODY"]),
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
            "frames": {},
        },
    )

    candles_15m = candles(130)
    candles_5m = candles(30)

    result = dual_mode_strategy.score_symbol(
        "FETUSDT",
        {"lastPrice": "100.0"},
        candles_15m,
        candles_5m,
    )

    # 15m macro support = 6, 5m near support = 16, volume = 8,
    # recovery confirmation = 4 => 34. RSI 48.66 contributes no points.
    assert result["scalp_gate"] is True
    assert result["scalp_recovery_confirmation"] is True
    assert result["scalp_score"] == 34
    assert result["scalp_score"] < dual_mode_strategy.SCALP_SCORE_THRESHOLD
    assert result["scalp_signal"] == "HOLD"
    assert result["trade_mode"] == "NONE"
