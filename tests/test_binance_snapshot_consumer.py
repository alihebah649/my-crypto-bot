from __future__ import annotations

import time
from pathlib import Path

import pytest

from core.binance_snapshot_consumer import BinanceSnapshotError, hydrate_market_data_manager
from core.market_data_manager import MarketDataManager, PersistentMarketDataCache


SYMBOLS = ["BTCUSDT", "ETHUSDT"]


def _candle(index: int) -> dict:
    return {
        "open_time": 1_000 + index * 10,
        "open": "100",
        "high": "101",
        "low": "99",
        "close": "100.5",
        "volume": "1000",
        "close_time": 1_005 + index * 10,
    }


def _snapshot(now_ms: int) -> dict:
    return {
        "schema_version": 1,
        "generated_at_ms": now_ms - 60_000,
        "source": "binance_spot_public_rest",
        "symbol_count": len(SYMBOLS),
        "symbols": {
            symbol: {
                "ticker": {"symbol": symbol, "lastPrice": "100.5"},
                "klines": {
                    interval: [_candle(i) for i in range(160)]
                    for interval in ("5m", "15m", "1h", "4h")
                },
            }
            for symbol in SYMBOLS
        },
    }


def test_hydrates_cache_with_expected_limits(monkeypatch, tmp_path: Path) -> None:
    now = time.time()
    monkeypatch.setattr(
        "core.binance_snapshot_consumer._fetch_json",
        lambda url, timeout: _snapshot(int(now * 1000)),
    )
    manager = MarketDataManager(
        PersistentMarketDataCache(tmp_path / "cache.json"),
        ticker_symbols=SYMBOLS,
    )

    result = hydrate_market_data_manager(
        manager,
        "https://example.invalid/latest.json",
        SYMBOLS,
        now=now,
    )

    assert result["loaded"] is True
    assert result["symbols"] == 2
    assert len(manager.cache.get("5m:BTCUSDT:60").payload) == 60
    assert len(manager.cache.get("15m:BTCUSDT:150").payload) == 150
    assert len(manager.cache.get("1h:BTCUSDT:60").payload) == 60
    assert len(manager.cache.get("4h:BTCUSDT:60").payload) == 60
    assert manager.cache.get("ticker:BTCUSDT").payload["symbol"] == "BTCUSDT"



def test_accepts_bounded_stale_snapshot_as_bootstrap(monkeypatch, tmp_path: Path) -> None:
    now = time.time()
    snapshot = _snapshot(int((now - 5 * 3600) * 1000))
    monkeypatch.setattr(
        "core.binance_snapshot_consumer._fetch_json",
        lambda url, timeout: snapshot,
    )
    manager = MarketDataManager(
        PersistentMarketDataCache(tmp_path / "cache.json"),
        ticker_symbols=SYMBOLS,
    )

    result = hydrate_market_data_manager(
        manager,
        "https://example.invalid/latest.json",
        SYMBOLS,
        now=now,
        max_stale_seconds=900,
        bootstrap_max_stale_seconds=21600,
    )

    assert result["loaded"] is True
    assert result["bootstrap_stale"] is True
    assert result["entry_fresh"] is False
    assert len(manager.cache.get("5m:BTCUSDT:60").payload) == 60

def test_rejects_stale_snapshot(monkeypatch, tmp_path: Path) -> None:
    now = time.time()
    snapshot = _snapshot(int(now * 1000) - 901_000)
    monkeypatch.setattr(
        "core.binance_snapshot_consumer._fetch_json",
        lambda url, timeout: snapshot,
    )
    manager = MarketDataManager(
        PersistentMarketDataCache(tmp_path / "cache.json"),
        ticker_symbols=SYMBOLS,
    )

    with pytest.raises(BinanceSnapshotError, match="too stale"):
        hydrate_market_data_manager(
            manager,
            "https://example.invalid/latest.json",
            SYMBOLS,
            now=now,
            max_stale_seconds=900,
            bootstrap_max_stale_seconds=900,
        )


def test_rejects_symbol_coverage_mismatch(monkeypatch, tmp_path: Path) -> None:
    now = time.time()
    snapshot = _snapshot(int(now * 1000))
    snapshot["symbols"].pop("ETHUSDT")
    snapshot["symbol_count"] = 1
    monkeypatch.setattr(
        "core.binance_snapshot_consumer._fetch_json",
        lambda url, timeout: snapshot,
    )
    manager = MarketDataManager(
        PersistentMarketDataCache(tmp_path / "cache.json"),
        ticker_symbols=SYMBOLS,
    )

    with pytest.raises(BinanceSnapshotError, match="symbol coverage"):
        hydrate_market_data_manager(
            manager,
            "https://example.invalid/latest.json",
            SYMBOLS,
            now=now,
        )


def test_rejects_unclosed_candle(monkeypatch, tmp_path: Path) -> None:
    now = time.time()
    snapshot = _snapshot(int(now * 1000))
    snapshot["symbols"]["BTCUSDT"]["klines"]["5m"][-1]["close_time"] = int(now * 1000) + 1
    monkeypatch.setattr(
        "core.binance_snapshot_consumer._fetch_json",
        lambda url, timeout: snapshot,
    )
    manager = MarketDataManager(
        PersistentMarketDataCache(tmp_path / "cache.json"),
        ticker_symbols=SYMBOLS,
    )

    with pytest.raises(BinanceSnapshotError, match="unclosed candle"):
        hydrate_market_data_manager(
            manager,
            "https://example.invalid/latest.json",
            SYMBOLS,
            now=now,
        )
