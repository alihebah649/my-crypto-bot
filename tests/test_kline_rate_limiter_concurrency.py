from __future__ import annotations

import importlib
import threading
import time


def test_kline_rate_limiter_does_not_hold_lock_during_network(monkeypatch):
    module = importlib.import_module("shadow_main")
    started = []
    release = threading.Event()

    def fake_underlying(symbol, interval, limit):
        started.append((symbol, time.monotonic()))
        release.wait(timeout=2.0)
        return [{"symbol": symbol, "interval": interval, "limit": limit}]

    monkeypatch.setattr(module, "_original_rate_limited_fetch_klines", fake_underlying)
    monkeypatch.setattr(module, "_binance_kline_last_request_at", 0.0)
    # Disable pacing in this unit test so it isolates the critical property:
    # the network call must not execute while the scheduling lock is held.
    monkeypatch.setattr(module, "_BINANCE_KLINE_MIN_INTERVAL", 0.0)

    results = []

    def worker(symbol):
        results.append(module._rate_limited_fetch_klines(symbol, "5m", 60))

    first = threading.Thread(target=worker, args=("A",))
    second = threading.Thread(target=worker, args=("B",))

    first.start()
    deadline = time.monotonic() + 1.0
    while len(started) < 1 and time.monotonic() < deadline:
        time.sleep(0.01)

    second.start()
    time.sleep(0.15)
    assert len(started) == 2, "Kline limiter is serializing network requests under its lock"

    release.set()
    first.join(timeout=2)
    second.join(timeout=2)
    assert len(results) == 2
