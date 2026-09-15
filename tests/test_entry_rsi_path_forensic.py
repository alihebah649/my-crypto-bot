from dual_mode_strategy import score_symbol


def _candle(open_price, high, low, close, volume=100.0):
    return {
        "open_time": 0,
        "open": float(open_price),
        "high": float(high),
        "low": float(low),
        "close": float(close),
        "volume": float(volume),
        "close_time": 1,
    }


def _series(count, price=100.0, volume=100.0):
    return [_candle(price, price * 1.001, price * 0.999, price, volume) for _ in range(count)]


def test_rsi_display_field_is_15m_while_scalp_gate_uses_5m(monkeypatch):
    """Prove 15m RSI is displayed while 5m RSI drives the scalp gate."""
    calls = []

    def fake_rsi(prices, period=14):
        calls.append(len(prices))
        return 57.21 if len(prices) >= 100 else 52.40

    monkeypatch.setattr("dual_mode_strategy.calculate_rsi", fake_rsi)
    monkeypatch.setattr(
        "dual_mode_strategy.analyze_multi_timeframe_context",
        lambda *_args, **_kwargs: {
            "available": False,
            "net": 0,
            "weighted_bull": 0,
            "weighted_bear": 0,
            "aligned_bullish": False,
            "weak_countertrend_recovery": False,
            "frames": {},
        },
    )
    monkeypatch.setattr("dual_mode_strategy.calculate_bollinger", lambda *_args, **_kwargs: (100.0, 101.0, 102.0))
    monkeypatch.setattr("dual_mode_strategy._volume_ratio", lambda *_args, **_kwargs: 1.20)
    monkeypatch.setattr("dual_mode_strategy.calculate_atr", lambda *_args, **_kwargs: 1.0)
    monkeypatch.setattr("dual_mode_strategy.calculate_ema", lambda *_args, **_kwargs: 99.0)
    monkeypatch.setattr("dual_mode_strategy.bullish_pattern", lambda *_args, **_kwargs: (True, "BULLISH_BREAKOUT", True))
    monkeypatch.setattr("dual_mode_strategy._scalp_recovery_confirmation", lambda *_args, **_kwargs: (True, 2, ["5M_RSI_RISING", "5M_BULLISH_BODY"]))

    result = score_symbol(
        "TESTUSDT",
        {"lastPrice": "100.0"},
        _series(150),
        _series(60),
    )

    assert result["rsi"] == 57.21
    assert result["rsi5m"] == 52.40
    assert result["scalp_max_rsi"] == 55.0
    assert "5M_RSI_TOO_HIGH" not in result["scalp_gate_reasons"]
    assert result["scalp_gate"] is True
    assert calls[:2] == [149, 59]
