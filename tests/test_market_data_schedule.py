from __future__ import annotations

from core.market_data_manager import CachePolicy, MarketDataManager, PersistentMarketDataCache


def test_default_policies_keep_short_and_long_timeframes_independent(tmp_path):
    manager = MarketDataManager(
        PersistentMarketDataCache(tmp_path / "market_cache.json"),
        ticker_symbols=["AUSDT", "BUSDT"],
        ticker_batch_size=1,
        ticker_group_interval_seconds=30,
    )

    assert manager.policies["ticker"].fresh_ttl_seconds < manager.policies["5m"].fresh_ttl_seconds
    assert manager.policies["5m"].fresh_ttl_seconds < manager.policies["15m"].fresh_ttl_seconds
    assert manager.policies["15m"].fresh_ttl_seconds < manager.policies["1h"].fresh_ttl_seconds
    assert manager.policies["1h"].fresh_ttl_seconds < manager.policies["4h"].fresh_ttl_seconds


def test_group_schedule_is_close_enough_for_short_lived_scalp_data(tmp_path):
    manager = MarketDataManager(
        PersistentMarketDataCache(tmp_path / "market_cache.json"),
        ticker_symbols=[f"S{i}USDT" for i in range(22)],
        ticker_batch_size=11,
        ticker_group_interval_seconds=30,
    )

    groups = manager.ticker_groups()
    assert max(abs((i + 1) * 30 - i * 30) for i in range(len(groups))) == 30
