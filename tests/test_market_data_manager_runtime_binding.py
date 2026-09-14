from __future__ import annotations

import threading
import time

from core.market_data_runtime_trace import install


class CacheStub:
    def __init__(self, rows=None):
        self.rows = dict(rows or {})

    def get(self, key):
        value = self.rows.get(key)
        if value is None:
            return None
        return type("Snapshot", (), {"fetched_at": value[0], "payload": value[1]})()

    def put(self, key, payload, fetched_at=None):
        self.rows[key] = (time.time() if fetched_at is None else fetched_at, payload)


class ManagerStub:
    def __init__(self, cache):
        self.cache = cache

    def get_for_analysis(self, dataset, key):
        return self.cache.get(key)


class LegacyStub:
    def __init__(self):
        self._market_data_runtime_trace_installed = False
        self.market_data_manager = None
        self.logger = type("Logger", (), {"info": lambda *a, **k: None})()

        def fetch_klines(symbol, interval, limit):
            return [{"open_time": 1, "close_time": 2, "close": 100.0}]

        def fetch_strategy_data():
            return {}, {}, {}

        def score_symbol(symbol, ticker, candles_15m, candles_5m):
            return {"symbol": symbol, "scalp_signal": "HOLD"}

        self.fetch_klines = fetch_klines
        self.fetch_strategy_data = fetch_strategy_data
        self.score_symbol = score_symbol


def test_runtime_trace_binds_to_actual_manager_cache_hit_path():
    now = time.time()
    expected = [{"close": 99.0}]
    cache = CacheStub({"5m:BTCUSDT:60": (now - 10.0, expected)})
    manager = ManagerStub(cache)
    legacy = LegacyStub()

    snapshot = install(
        legacy=legacy,
        kline_cache={},
        kline_cache_lock=threading.RLock(),
        kline_cache_ttl={"5m": 310.0},
    )

    def managed_kline(symbol, interval, limit):
        key = f"{interval}:{symbol}:{limit}"
        cached = manager.get_for_analysis(interval, key)
        if cached is not None:
            return cached.payload
        data = legacy._raw_fetch(symbol, interval, limit)
        manager.cache.put(key, data)
        return data

    legacy._raw_fetch = legacy.fetch_klines
    legacy.fetch_klines = managed_kline
    legacy._market_data_runtime_trace_bind_manager(manager)

    result = legacy.fetch_klines("BTCUSDT", "5m", 60)

    assert result == expected
    event = snapshot()["last_events"][-1]
    assert event["active_source"] == "MARKET_DATA_MANAGER"
    assert event["manager_cache_key"] == "5m:BTCUSDT:60"
    assert event["manager_cache_age_seconds"] >= 10.0
    assert event["source"] == "CACHE"


def test_runtime_trace_records_manager_refresh_source():
    now = time.time()
    cache = CacheStub()
    manager = ManagerStub(cache)
    legacy = LegacyStub()

    snapshot = install(
        legacy=legacy,
        kline_cache={},
        kline_cache_lock=threading.RLock(),
        kline_cache_ttl={"5m": 310.0},
    )

    original = legacy.fetch_klines

    def managed_kline(symbol, interval, limit):
        key = f"{interval}:{symbol}:{limit}"
        cached = manager.get_for_analysis(interval, key)
        if cached is not None:
            return cached.payload
        data = original(symbol, interval, limit)
        manager.cache.put(key, data, fetched_at=now)
        return data

    legacy.fetch_klines = managed_kline
    legacy._market_data_runtime_trace_bind_manager(manager)

    result = legacy.fetch_klines("ETHUSDT", "5m", 60)

    assert result
    event = snapshot()["last_events"][-1]
    assert event["active_source"] == "MARKET_DATA_MANAGER"
    assert event["source"] == "REFRESHED"
    assert event["manager_cache_key"] == "5m:ETHUSDT:60"
