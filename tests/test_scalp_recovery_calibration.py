from __future__ import annotations

import dual_mode_strategy


def candle(open_price: float, high: float, low: float, close: float, volume: float = 100.0) -> dict:
    return {"open": open_price, "high": high, "low": low, "close": close, "volume": volume}


def candles(count: int = 130) -> list[dict]:
    return [candle(100.0, 101.0, 99.0, 100.0, 100.0) for _ in range(count)]


def _neutral_mtf(data):
    return {
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
    }


def _run(monkeypatch, recovery):
    monkeypatch.setattr(dual_mode_strategy, "calculate_rsi", lambda prices, period=14: 48.66)
    monkeypatch.setattr(
        dual_mode_strategy,
        "calculate_bollinger",
        lambda candles, period=20, deviations=2.0: (
            (95.0, 110.0, 121.0) if len(candles) >= 100 else (99.5, 110.0, 121.0)
        ),
    )
    monkeypatch.setattr(dual_mode_strategy, "_volume_ratio", lambda candles, window=20: 1.127)
    monkeypatch.setattr(dual_mode_strategy, "bullish_pattern", lambda candles: (False, "NEUTRAL", False))
    monkeypatch.setattr(dual_mode_strategy, "analyze_multi_timeframe_context", _neutral_mtf)
    monkeypatch.setattr(
        dual_mode_strategy,
        "_scalp_recovery_confirmation",
        lambda candles, current_rsi: recovery,
    )
    return dual_mode_strategy.score_symbol(
        "FETUSDT",
        {"lastPrice": "100.0"},
        candles(),
        candles(30),
    )


def test_recovery_bonus_is_only_applied_when_confirmation_exists(monkeypatch):
    without_recovery = _run(monkeypatch, (False, 0, []))
    with_recovery = _run(
        monkeypatch,
        (True, 2, ["5M_PRICE_RECOVERY", "5M_BULLISH_BODY"]),
    )

    assert without_recovery["scalp_gate"] is False
    assert without_recovery["scalp_score"] == 30
    assert with_recovery["scalp_gate"] is True
    assert with_recovery["scalp_recovery_confirmation"] is True
    assert with_recovery["scalp_score"] == 34
    assert with_recovery["scalp_score"] - without_recovery["scalp_score"] == dual_mode_strategy.SCALP_RECOVERY_POINTS
    assert with_recovery["scalp_signal"] == "HOLD"
