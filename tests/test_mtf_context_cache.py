from core.mtf_context_cache import MTFContextCache


def test_cache_returns_fresh_context_without_refetch():
    now = [100.0]
    cache = MTFContextCache(ttl_by_timeframe={"1h": 3300.0, "4h": 14100.0}, clock=lambda: now[0])
    candles = [{"close_time": 123}]
    cache.put("SOLUSDT", "1h", candles)

    assert cache.get("SOLUSDT", "1h") == candles
    assert cache.size() == 1


def test_cache_expires_only_after_timeframe_ttl():
    now = [100.0]
    cache = MTFContextCache(ttl_by_timeframe={"1h": 3300.0}, clock=lambda: now[0])
    cache.put("SOLUSDT", "1h", [{"close_time": 123}])

    now[0] = 3399.9
    assert cache.get("SOLUSDT", "1h") is not None

    now[0] = 3400.0
    assert cache.get("SOLUSDT", "1h") is None
    assert cache.size() == 0


def test_cache_isolated_by_symbol_and_timeframe():
    cache = MTFContextCache(ttl_by_timeframe={"1h": 3300.0, "4h": 14100.0})
    cache.put("SOLUSDT", "1h", [{"close_time": 1}])
    cache.put("BTCUSDT", "4h", [{"close_time": 2}])

    assert cache.get("SOLUSDT", "4h") is None
    assert cache.get("BTCUSDT", "1h") is None
    assert cache.get("SOLUSDT", "1h") == [{"close_time": 1}]
    assert cache.get("BTCUSDT", "4h") == [{"close_time": 2}]
