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
    """Lock the forensic distinction behind the observed Telegram symptom.

    The live BUY message reads score['rsi'], while the dual-mode scalp gate
    evaluates r5 (the 5m RSI). This test makes those values intentionally
    different and proves the gate follows 5m RSI rather than the displayed
    15m RSI.
    """
    calls = []

    def fake_rsi(prices, period=14):
        calls.append(len(prices))
        # score_symbol calculates 15m RSI before 5m RSI.
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

    candles_15m = _series(150)
    candles_5m = _series(60)
    # Make the latest closed 5m candles a confirmed bullish breakout so the
    # gate can succeed without changing any production thresholds.
    candles_5m[-3] = _candle(99.0, 100.0, 98.8, 99.5, 120.0)
    candles_5m[-2] = _candle(99.5, 100.5, 99.4, 99.8, 130.0)
    candles_5m[-1] = _candle(99.8, 101.5, 99.7, 101.0, 150.0)

    result = score_symbol(
        "TESTUSDT",
        {"lastPrice": "101.0"},
        candles_15m,
        candles_5m,
    )

    assert result["rsi"] == 57.21
    assert result["rsi5m"] == 52.40
    assert result["scalp_max_rsi"] == 55.0
    assert "5M_RSI_TOO_HIGH" not in result["scalp_gate_reasons"]
    assert result["scalp_gate"] is True
    assert calls[:2] == [149, 59]
