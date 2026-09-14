from __future__ import annotations

import importlib
import time


def test_kline_cache_expires_by_interval(monkeypatch):
    base = importlib.import_module("shadow_main_base")
    calls = []

    def fake_fetch(symbol, interval, limit):
        calls.append((symbol, interval, limit))
        return [{"open_time": len(calls), "close": 1.0}]

    monkeypatch.setattr(base, "_original_fetch_klines", fake_fetch)
    monkeypatch.setattr(base, "_binance_guard_active", lambda: False)

    key = ("TESTUSDT", "5m", 60)
    base._kline_cache.pop(key, None)

    first = base._guarded_fetch_klines(*key)
    second = base._guarded_fetch_klines(*key)
    assert first == second
    assert len(calls) == 1

    original_time = base.time.time
    monkeypatch.setattr(base.time, "time", lambda: original_time() + base._KLINE_CACHE_TTL["5m"] + 1)
    third = base._guarded_fetch_klines(*key)
    assert third != first
    assert len(calls) == 2


def test_legacy_strategy_cycle_resolves_current_kline_wrapper(monkeypatch):
    base = importlib.import_module("shadow_main_base")
    legacy = base._legacy

    seen = []
    original_strategy = base._original_fetch_strategy_data

    def fake_strategy():
        return ({"TESTUSDT": {"lastPrice": "1", "bidPrice": "1", "askPrice": "1", "quoteVolume": "1"}}, {}, {})

    def fake_mtf():
        return {symbol: {"1h": [], "4h": []} for symbol in legacy.TRADING_SYMBOLS}

    monkeypatch.setattr(base, "_original_fetch_strategy_data", fake_strategy)
    monkeypatch.setattr(base, "_fetch_mtf_context", fake_mtf)

    original_fetch_klines = legacy.fetch_klines
    legacy.fetch_klines = lambda symbol, interval, limit: seen.append((symbol, interval, limit)) or []
    try:
        result = legacy.fetch_strategy_data()
        assert result[0]["TESTUSDT"]["lastPrice"] == "1"
        # The wrapper must still resolve through the legacy module's current globals.
        assert legacy.fetch_strategy_data is base._fetch_strategy_data_with_mtf
    finally:
        legacy.fetch_klines = original_fetch_klines
        base._original_fetch_strategy_data = original_strategy
