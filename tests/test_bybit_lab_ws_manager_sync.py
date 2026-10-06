from __future__ import annotations

import importlib
import time


def test_bybit_lab_sync_uses_latest_ws_row_even_when_rest_seed_rows_lack_closed_flags(monkeypatch):
    base = importlib.import_module("shadow_main_base")
    monkeypatch.setattr(base, "PAPER_VENUE_MODE", "BYBIT_ONLY_LAB")

    now = time.time()
    seeded = [
        {
            "open_time": i * 300_000,
            "close_time": i * 300_000 + 299_999,
            "close": 100.0,
            "market_data_transport": "REST_COLD_START",
        }
        for i in range(1, 60)
    ]
    live_open = {
        "open_time": 60 * 300_000,
        "close_time": 60 * 300_000 + 299_999,
        "close": 101.0,
        "is_closed": False,
        "received_at": now,
        "market_data_transport": "WEBSOCKET",
    }
    rows = seeded + [live_open]

    class Cache:
        def __init__(self):
            self.put_calls = []

        def put(self, key, payload, *, fetched_at=None, persist=True):
            self.put_calls.append((key, payload, fetched_at, persist))

    class Manager:
        def __init__(self):
            self.cache = Cache()

    class Stream:
        stale_after_seconds = 30.0

        def snapshot(self):
            return {"event_stream_healthy": True}

    manager = Manager()
    assert base._sync_bybit_ws_kline_manager_cache(
        manager,
        "5m:FETUSDT:60",
        rows,
        Stream(),
    )

    assert len(manager.cache.put_calls) == 1
    key, payload, fetched_at, persist = manager.cache.put_calls[0]
    assert key == "5m:FETUSDT:60"
    assert payload is rows
    assert fetched_at is not None
    assert abs(fetched_at - now) < 2.0
    assert persist is False


def test_bybit_lab_closed_ws_row_uses_candle_close_time_not_receive_time(monkeypatch):
    base = importlib.import_module("shadow_main_base")
    monkeypatch.setattr(base, "PAPER_VENUE_MODE", "BYBIT_ONLY_LAB")

    now = time.time()
    close_time = int((now - 75.0) * 1000)
    rows = [
        {
            "open_time": 1,
            "close_time": 299_999,
            "close": 100.0,
            "market_data_transport": "REST_COLD_START",
        },
        {
            "open_time": 300_000,
            "close_time": close_time,
            "close": 101.0,
            "is_closed": True,
            "received_at": now - 70.0,
            "market_data_transport": "WEBSOCKET",
        },
    ]

    class Cache:
        def __init__(self):
            self.put_calls = []

        def put(self, key, payload, *, fetched_at=None, persist=True):
            self.put_calls.append((key, payload, fetched_at, persist))

    class Manager:
        def __init__(self):
            self.cache = Cache()

    class Stream:
        stale_after_seconds = 30.0

        def snapshot(self):
            return {"event_stream_healthy": True}

    manager = Manager()
    assert base._sync_bybit_ws_kline_manager_cache(
        manager,
        "5m:FETUSDT:60",
        rows,
        Stream(),
    )

    _, _, fetched_at, persist = manager.cache.put_calls[0]
    assert fetched_at is not None
    assert abs(fetched_at - close_time / 1000.0) < 0.01
    assert persist is False


def test_bybit_lab_does_not_refresh_from_stale_ws_row(monkeypatch):
    base = importlib.import_module("shadow_main_base")
    monkeypatch.setattr(base, "PAPER_VENUE_MODE", "BYBIT_ONLY_LAB")

    now = time.time()
    rows = [{
        "open_time": 300_000,
        "close_time": int((now - 10.0) * 1000),
        "close": 101.0,
        "is_closed": False,
        "received_at": now - 31.0,
        "market_data_transport": "WEBSOCKET",
    }]

    class Cache:
        def __init__(self):
            self.put_calls = []

        def put(self, *args, **kwargs):
            self.put_calls.append((args, kwargs))

    class Manager:
        def __init__(self):
            self.cache = Cache()

    class Stream:
        stale_after_seconds = 30.0

        def snapshot(self):
            return {"event_stream_healthy": True}

    manager = Manager()
    assert base._sync_bybit_ws_kline_manager_cache(
        manager,
        "5m:FETUSDT:60",
        rows,
        Stream(),
    ) is False
    assert manager.cache.put_calls == []


def test_binance_lab_path_remains_ws_only_for_cold_start():
    base = (importlib.import_module("shadow_main_base"))
    source = open(base.__file__, "r", encoding="utf-8").read()
    assert 'if PAPER_VENUE_MODE == "BINANCE_ONLY_LAB":' in source
    assert 'There is deliberately no REST' in source
    assert 'waiting_for_closed_ws_history' in source
