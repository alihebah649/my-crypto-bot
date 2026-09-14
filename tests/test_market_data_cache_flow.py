from __future__ import annotations

import importlib


def test_kline_cache_expires_for_5m_and_15m(monkeypatch):
    base = importlib.import_module("shadow_main_base")
    calls = []

    def fake_fetch(symbol, interval, limit):
        calls.append((symbol, interval, limit))
        return [{"open_time": len(calls), "close": float(len(calls))}]

    monkeypatch.setattr(base, "_original_fetch_klines", fake_fetch)
    monkeypatch.setattr(base, "_binance_guard_active", lambda: False)

    for interval, limit in (("5m", 60), ("15m", 150)):
        key = ("TESTUSDT", interval, limit)
        base._kline_cache.pop(key, None)
        first = base._guarded_fetch_klines(*key)
        second = base._guarded_fetch_klines(*key)
        assert first == second
        assert calls.count(("TESTUSDT", interval, limit)) == 1

        cached_at = base._kline_cache[key][0]
        original_time = base.time.time
        monkeypatch.setattr(base.time, "time", lambda: cached_at + base._KLINE_CACHE_TTL[interval] + 1)
        third = base._guarded_fetch_klines(*key)
        assert third != first
        assert calls.count(("TESTUSDT", interval, limit)) == 2
        monkeypatch.setattr(base.time, "time", original_time)


def test_real_legacy_strategy_fetch_uses_current_kline_wrapper(monkeypatch):
    base = importlib.import_module("shadow_main_base")
    legacy = base._legacy
    original_symbols = list(legacy.TRADING_SYMBOLS)
    original_fetch_24h = legacy.fetch_24h_tickers
    original_fetch_klines = legacy.fetch_klines
    try:
        legacy.TRADING_SYMBOLS[:] = ["TESTUSDT"]
        monkeypatch.setattr(legacy, "fetch_24h_tickers", lambda: {"TESTUSDT": {"lastPrice": "1", "bidPrice": "1", "askPrice": "1", "quoteVolume": "1"}})
        seen = []
        legacy.fetch_klines = lambda symbol, interval, limit: seen.append((symbol, interval, limit)) or [{"open_time": 1, "close": 1.0}]
        result = base._original_fetch_strategy_data()
        assert result[0]["TESTUSDT"]["lastPrice"] == "1"
        assert set(seen) == {
            ("TESTUSDT", "15m", 150),
            ("TESTUSDT", "5m", 60),
        }
    finally:
        legacy.TRADING_SYMBOLS[:] = original_symbols
        legacy.fetch_24h_tickers = original_fetch_24h
        legacy.fetch_klines = original_fetch_klines


def test_patched_strategy_wrapper_preserves_mtf_stage(monkeypatch):
    base = importlib.import_module("shadow_main_base")
    legacy = base._legacy
    original_strategy = base._original_fetch_strategy_data
    original_mtf = base._fetch_mtf_context
    try:
        monkeypatch.setattr(base, "_original_fetch_strategy_data", lambda: ({"TESTUSDT": {"lastPrice": "1"}}, {}, {}))
        seen = []
        monkeypatch.setattr(base, "_fetch_mtf_context", lambda: (seen.append("mtf") or {"TESTUSDT": {"1h": [], "4h": []}}))
        result = legacy.fetch_strategy_data()
        assert result[0]["TESTUSDT"]["lastPrice"] == "1"
        assert seen == ["mtf"]
        assert legacy.fetch_strategy_data is base._fetch_strategy_data_with_mtf
    finally:
        base._original_fetch_strategy_data = original_strategy
        base._fetch_mtf_context = original_mtf
