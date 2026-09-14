from __future__ import annotations

import importlib
import time


def _load_core_init_module():
    return importlib.import_module("core")


def test_managed_kline_refreshes_after_fresh_ttl(monkeypatch, tmp_path):
    core = _load_core_init_module()
    manager_module = importlib.import_module("core.market_data_manager")

    class FakeLegacy:
        PAPER_STATE_DIR = str(tmp_path)
        TRADING_SYMBOLS = ["BTCUSDT"]

        def __init__(self):
            self.fetch_24h_tickers = lambda: {}
            self.calls = []
            self.logger = type("Logger", (), {"info": lambda *a, **k: None, "warning": lambda *a, **k: None, "exception": lambda *a, **k: None})()

        def fetch_klines(self, symbol, interval, limit):
            self.calls.append((symbol, interval, limit))
            return [{"open_time": len(self.calls), "close": float(len(self.calls))}]

        def _binance_get(self, *args, **kwargs):
            return []

    legacy = FakeLegacy()
    monkeypatch.setattr(core, "_find_legacy", lambda: legacy)
    monkeypatch.setattr(core, "_find_shadow_main", lambda: None)

    # Prevent the background ticker loop from running during this unit test.
    monkeypatch.setattr(core.time, "sleep", lambda _seconds: None)

    assert core._install_market_data_layer() is True
    manager = legacy.market_data_manager
    key = "5m:BTCUSDT:60"

    fresh_payload = [{"open_time": 100, "close": 10.0}]
    stale_payload = [{"open_time": 101, "close": 11.0}]
    now = time.time()
    manager.cache.put(key, fresh_payload, fetched_at=now - manager.policies["5m"].fresh_ttl_seconds + 1)

    fresh = legacy.fetch_klines("BTCUSDT", "5m", 60)
    assert fresh == fresh_payload
    assert legacy.calls == []

    manager.cache.put(key, stale_payload, fetched_at=now - manager.policies["5m"].fresh_ttl_seconds - 1)
    refreshed = legacy.fetch_klines("BTCUSDT", "5m", 60)

    assert refreshed != stale_payload
    assert legacy.calls == [("BTCUSDT", "5m", 60)]
    assert manager.cache.get(key).payload == refreshed


def test_stale_manager_snapshot_can_still_fallback_on_refresh_failure(monkeypatch, tmp_path):
    core = _load_core_init_module()

    class FakeLegacy:
        PAPER_STATE_DIR = str(tmp_path)
        TRADING_SYMBOLS = ["BTCUSDT"]

        def __init__(self):
            self.fetch_24h_tickers = lambda: {}
            self.logger = type("Logger", (), {"info": lambda *a, **k: None, "warning": lambda *a, **k: None, "exception": lambda *a, **k: None})()

        def fetch_klines(self, symbol, interval, limit):
            raise RuntimeError("refresh unavailable")

        def _binance_get(self, *args, **kwargs):
            return []

    legacy = FakeLegacy()
    monkeypatch.setattr(core, "_find_legacy", lambda: legacy)
    monkeypatch.setattr(core, "_find_shadow_main", lambda: None)
    monkeypatch.setattr(core.time, "sleep", lambda _seconds: None)

    assert core._install_market_data_layer() is True
    manager = legacy.market_data_manager
    key = "5m:BTCUSDT:60"
    stale_payload = [{"open_time": 101, "close": 11.0}]
    manager.cache.put(
        key,
        stale_payload,
        fetched_at=time.time() - manager.policies["5m"].fresh_ttl_seconds - 1,
    )

    assert legacy.fetch_klines("BTCUSDT", "5m", 60) == stale_payload
