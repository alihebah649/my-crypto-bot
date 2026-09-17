from __future__ import annotations


def _candle(value: float) -> dict:
    return {
        "open": value,
        "high": value + 0.5,
        "low": value - 0.5,
        "close": value + 0.2,
        "volume": 100.0,
    }


def test_paper_runtime_passes_cached_1h_and_4h_context_into_dual_lane_strategy(monkeypatch):
    import shadow_main_base

    calls = {}

    def fake_score_symbol(symbol, ticker, candles_15m, candles_5m, candles_1h=None, candles_4h=None):
        calls["symbol"] = symbol
        calls["candles_15m"] = candles_15m
        calls["candles_5m"] = candles_5m
        calls["candles_1h"] = candles_1h
        calls["candles_4h"] = candles_4h
        return {"symbol": symbol, "score": 0, "signal": "HOLD"}

    monkeypatch.setattr(shadow_main_base, "score_symbol", fake_score_symbol)
    candles_15m = [_candle(100 + i) for i in range(12)]
    candles_5m = [_candle(100 + i) for i in range(12)]
    candles_1h = [_candle(200 + i) for i in range(12)]
    candles_4h = [_candle(300 + i) for i in range(12)]
    monkeypatch.setitem(
        shadow_main_base._mtf_candles,
        "TESTUSDT",
        {"1h": candles_1h, "4h": candles_4h},
    )

    result = shadow_main_base._score_symbol_with_mtf(
        "TESTUSDT",
        {"lastPrice": "101.0"},
        candles_15m,
        candles_5m,
    )

    assert result["symbol"] == "TESTUSDT"
    assert calls["candles_15m"] is candles_15m
    assert calls["candles_5m"] is candles_5m
    assert calls["candles_1h"] is candles_1h
    assert calls["candles_4h"] is candles_4h


def test_paper_runtime_mtf_cache_keeps_timeframes_distinct():
    import shadow_main_base

    context = {
        "TESTUSDT": {
            "1h": [_candle(201 + i) for i in range(8)],
            "4h": [_candle(401 + i) for i in range(8)],
        }
    }
    shadow_main_base._mtf_candles.clear()
    shadow_main_base._mtf_candles.update(context)

    stored = shadow_main_base._mtf_candles["TESTUSDT"]
    assert stored["1h"][0]["open"] == 201
    assert stored["4h"][0]["open"] == 401
