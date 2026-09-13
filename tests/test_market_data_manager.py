from __future__ import annotations

from pathlib import Path

from core.market_data_manager import CachePolicy, MarketDataManager, PersistentMarketDataCache


def test_ticker_groups_split_into_eleven_and_eleven(tmp_path: Path):
    symbols = [f"S{i}USDT" for i in range(22)]
    manager = MarketDataManager(
        PersistentMarketDataCache(tmp_path / "market_cache.json"),
        ticker_symbols=symbols,
        ticker_batch_size=11,
        ticker_group_interval_seconds=120,
    )

    groups = manager.ticker_groups()

    assert [len(group) for group in groups] == [11, 11]
    assert groups[0] == symbols[:11]
    assert groups[1] == symbols[11:]


def test_only_one_ticker_group_refreshes_per_interval(tmp_path: Path):
    cache = PersistentMarketDataCache(tmp_path / "market_cache.json")
    manager = MarketDataManager(
        cache,
        ticker_symbols=[f"S{i}USDT" for i in range(22)],
        ticker_batch_size=11,
        ticker_group_interval_seconds=120,
    )
    calls: list[list[str]] = []

    def fetch(batch: list[str]):
        calls.append(batch)
        return {symbol: {"lastPrice": "1"} for symbol in batch}

    assert manager.refresh_ticker_group(fetch, now=1000.0)
    assert manager.refresh_ticker_group(fetch, now=1000.0) == {}
    assert manager.refresh_ticker_group(fetch, now=1119.0) == {}
    assert manager.refresh_ticker_group(fetch, now=1120.0)

    assert len(calls) == 2
    assert calls[0] != calls[1]
    assert len(manager.merged_ticker_snapshot()) == 22


def test_cache_survives_reload_and_stale_data_is_not_entry_safe(tmp_path: Path):
    path = tmp_path / "market_cache.json"
    cache = PersistentMarketDataCache(path)
    cache.put("ticker:BTCUSDT", {"lastPrice": "100"}, fetched_at=1000.0)
    cache.put("1h:BTCUSDT", [{"close": 100}], fetched_at=1000.0)

    reloaded = PersistentMarketDataCache(path)
    manager = MarketDataManager(
        reloaded,
        ticker_symbols=["BTCUSDT"],
        policies={
            "ticker": CachePolicy(fresh_ttl_seconds=180.0, stale_max_age_seconds=900.0),
            "1h": CachePolicy(fresh_ttl_seconds=3610.0, stale_max_age_seconds=7200.0),
        },
    )

    assert reloaded.get("ticker:BTCUSDT").payload["lastPrice"] == "100"
    assert manager.get_for_analysis("ticker", "ticker:BTCUSDT", now=1500.0) is not None
    assert not manager.entry_data_is_fresh("ticker", "ticker:BTCUSDT", now=1500.0)
    assert manager.entry_data_is_fresh("ticker", "ticker:BTCUSDT", now=1100.0)
    assert manager.entry_data_is_fresh("1h", "1h:BTCUSDT", now=1500.0)
