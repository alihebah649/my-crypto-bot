from __future__ import annotations

from core.market_data_manager import MarketDataManager, PersistentMarketDataCache


def test_ticker_scheduler_uses_short_group_gap(tmp_path):
    manager = MarketDataManager(
        PersistentMarketDataCache(tmp_path / "market_cache.json"),
        ticker_symbols=[f"S{i}USDT" for i in range(22)],
        ticker_batch_size=11,
        ticker_group_interval_seconds=30,
    )
    assert [len(group) for group in manager.ticker_groups()] == [11, 11]
    assert manager.ticker_group_interval_seconds == 30.0
