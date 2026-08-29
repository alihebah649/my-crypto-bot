from __future__ import annotations

from dual_mode_strategy import score_symbol


def candle(o, h, l, c, volume=100.0):
    return {"open": o, "high": h, "low": l, "close": c, "volume": volume}


def rising(count=130, start=100.0):
    return [candle(start + i * 0.05, start + i * 0.08, start + i * 0.02, start + i * 0.06) for i in range(count)]


def bearish(count=60, start=110.0):
    return [candle(start - i * 0.2, start - i * 0.1, start - i * 0.3, start - i * 0.25) for i in range(count)]


def test_optional_mtf_arguments_preserve_existing_contract():
    result = score_symbol("TESTUSDT", {"lastPrice": "106.5"}, rising(), rising(30))
    assert result["mtf_context_available"] is True
    assert set(result["mtf_timeframe_bias"]) == {"5m", "15m", "1h", "4h"}


def test_strong_higher_timeframe_bearish_context_can_veto_weak_scalp_recovery(monkeypatch):
    monkeypatch.setattr("dual_mode_strategy.calculate_rsi", lambda prices, period=14: 35.0)
    monkeypatch.setattr("dual_mode_strategy.calculate_bollinger", lambda candles, period=20, deviations=2.0: (100.0, 110.0, 120.0))
    monkeypatch.setattr("dual_mode_strategy._volume_ratio", lambda candles, window=20: 1.20)
    monkeypatch.setattr("dual_mode_strategy.bullish_pattern", lambda candles: (False, "NEUTRAL", False))

    c15 = bearish(130)
    c5 = [candle(100.0, 100.2, 99.7, 99.8) for _ in range(30)]
    c5[-3] = candle(99.5, 99.7, 98.5, 98.8)
    c5[-2] = candle(98.8, 99.0, 98.2, 98.7)
    c1h = bearish(60)
    c4h = bearish(60)

    result = score_symbol("TESTUSDT", {"lastPrice": "98.7"}, c15, c5, c1h, c4h)

    assert result["mtf_higher_timeframes_bearish"] is True
    assert result["mtf_countertrend_warning"] is True
    assert result["mtf_countertrend_veto"] is True
    assert result["scalp_signal"] == "HOLD"
    assert "MTF_STRONG_COUNTERTREND_VETO" in result["scalp_gate_reasons"]


def test_confirmed_5m_reversal_is_not_blocked_by_higher_timeframe_context(monkeypatch):
    monkeypatch.setattr("dual_mode_strategy.bullish_pattern", lambda candles: (True, "BULLISH_BREAKOUT", True))
    c15 = bearish(130)
    c5 = rising(30, 100.0)
    c1h = bearish(60)
    c4h = bearish(60)

    result = score_symbol("TESTUSDT", {"lastPrice": "106.0"}, c15, c5, c1h, c4h)

    assert result["mtf_higher_timeframes_bearish"] is True
    assert result["mtf_countertrend_veto"] is False
