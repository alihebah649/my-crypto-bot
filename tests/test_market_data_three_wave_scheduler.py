from __future__ import annotations

from core.market_data_manager import MarketDataManager, PersistentMarketDataCache


def build_manager(tmp_path):
    return MarketDataManager(
        PersistentMarketDataCache(tmp_path / "cache.json"),
        ticker_symbols=[
            "BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "ADAUSDT",
            "DOTUSDT", "NEARUSDT", "ARBUSDT", "OPUSDT", "BNBUSDT",
            "AVAXUSDT", "ALGOUSDT", "ATOMUSDT", "FETUSDT", "LTCUSDT",
            "XRPUSDT", "XLMUSDT", "HBARUSDT", "SUIUSDT", "BCHUSDT",
            "TRXUSDT", "RENDERUSDT",
        ],
        kline_wave_count=3,
        kline_wave_interval_seconds=30.0,
    )


def test_kline_waves_split_universe_deterministically(tmp_path):
    manager = build_manager(tmp_path)

    groups = manager.kline_wave_groups()

    assert [len(group) for group in groups] == [8, 7, 7]
    assert groups[0][:3] == ["BTCUSDT", "ARBUSDT", "AVAXUSDT"]
    assert groups[1][:3] == ["ETHUSDT", "OPUSDT", "ALGOUSDT"]
    assert groups[2][:3] == ["SOLUSDT", "BNBUSDT", "ATOMUSDT"]
    assert sorted(symbol for group in groups for symbol in group) == sorted(manager.symbols)


def test_kline_wave_claim_is_single_slot_and_round_robin(tmp_path):
    manager = build_manager(tmp_path)

    first = manager.claim_kline_refresh_wave(now=100.0)
    same_slot = manager.claim_kline_refresh_wave(now=110.0)
    second = manager.claim_kline_refresh_wave(now=130.0)
    third = manager.claim_kline_refresh_wave(now=160.0)
    fourth = manager.claim_kline_refresh_wave(now=190.0)

    assert first["claimed"] is True
    assert first["wave_index"] == 0
    assert same_slot["claimed"] is False
    assert same_slot["wave_index"] == 0
    assert second["claimed"] is True
    assert second["wave_index"] == 1
    assert third["claimed"] is True
    assert third["wave_index"] == 2
    assert fourth["claimed"] is True
    assert fourth["wave_index"] == 0

    assert set(first["symbols"]).isdisjoint(second["symbols"])
    assert set(second["symbols"]).isdisjoint(third["symbols"])
    assert set(first["symbols"]).isdisjoint(third["symbols"])


def test_kline_wave_snapshot_exposes_scheduler_state(tmp_path):
    manager = build_manager(tmp_path)
    manager.claim_kline_refresh_wave(now=100.0)

    snapshot = manager.kline_wave_snapshot()

    assert snapshot["wave_count"] == 3
    assert snapshot["wave_interval_seconds"] == 30.0
    assert snapshot["wave_index"] == 0
    assert snapshot["symbols"]
    assert snapshot["next_wave_in_seconds"] >= 0.0
