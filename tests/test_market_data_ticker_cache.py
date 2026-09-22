import shadow_main


def test_ticker_cache_uses_fresh_snapshot_without_upstream_call(monkeypatch):
    original = {"BTCUSDT": {"lastPrice": "100.0"}}
    calls = {"count": 0}

    def upstream():
        calls["count"] += 1
        return original

    monkeypatch.setattr(shadow_main, "_paper_original_24h_tickers", upstream)
    monkeypatch.setattr(shadow_main.time, "time", lambda: 1000.0)
    monkeypatch.setattr(shadow_main, "_ticker_cache", None)
    monkeypatch.setattr(shadow_main, "_ticker_cache_hits", 0)
    monkeypatch.setattr(shadow_main, "_ticker_cache_misses", 0)
    monkeypatch.setattr(shadow_main, "_ticker_cache_stale_uses", 0)
    # These tests target the legacy cache fallback contract in isolation.
    monkeypatch.setattr(shadow_main, "_market_data_manager", None)

    first = shadow_main._guarded_fetch_24h_tickers_with_cache()
    second = shadow_main._guarded_fetch_24h_tickers_with_cache()

    assert first == original
    assert second == original
    assert calls["count"] == 1
    assert shadow_main._ticker_cache_hits == 1


def test_ticker_cache_uses_bounded_stale_snapshot_when_binance_returns_empty(monkeypatch):
    original = {"BTCUSDT": {"lastPrice": "100.0"}}
    calls = {"count": 0}
    now = {"value": 1000.0}

    def upstream():
        calls["count"] += 1
        return original if calls["count"] == 1 else {}

    monkeypatch.setattr(shadow_main, "_paper_original_24h_tickers", upstream)
    monkeypatch.setattr(shadow_main.time, "time", lambda: now["value"])
    monkeypatch.setattr(shadow_main, "_ticker_cache", None)
    monkeypatch.setattr(shadow_main, "_ticker_cache_hits", 0)
    monkeypatch.setattr(shadow_main, "_ticker_cache_misses", 0)
    monkeypatch.setattr(shadow_main, "_ticker_cache_stale_uses", 0)
    # Isolate the legacy fallback contract from the active manager aggregation.
    monkeypatch.setattr(shadow_main, "_market_data_manager", None)

    assert shadow_main._guarded_fetch_24h_tickers_with_cache() == original

    now["value"] = 1300.0  # cache is stale relative to 5-minute fresh TTL, but within 15-minute fallback
    assert shadow_main._guarded_fetch_24h_tickers_with_cache() == original
    assert shadow_main._ticker_cache_stale_uses == 1
    assert calls["count"] == 2

    now["value"] = 1901.0  # outside the bounded stale window
    assert shadow_main._guarded_fetch_24h_tickers_with_cache() == {}
    assert calls["count"] == 3
