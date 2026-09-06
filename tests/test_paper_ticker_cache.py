from __future__ import annotations

from unittest.mock import patch

import shadow_main


def reset_ticker_cache() -> None:
    shadow_main._ticker_cache = None
    shadow_main._ticker_cache_hits = 0
    shadow_main._ticker_cache_misses = 0
    shadow_main._ticker_cache_stale_uses = 0


def test_ticker_cache_reuses_fresh_snapshot_without_exchange_request():
    reset_ticker_cache()
    calls = []
    payload = {"BTCUSDT": {"symbol": "BTCUSDT", "lastPrice": "80000"}}

    def succeed():
        calls.append("request")
        return payload

    with patch.object(shadow_main, "_paper_original_24h_tickers", side_effect=succeed):
        first = shadow_main._guarded_fetch_24h_tickers_with_cache()
        second = shadow_main._guarded_fetch_24h_tickers_with_cache()

    assert first == second == payload
    assert calls == ["request"]
    assert shadow_main._ticker_cache_hits == 1
    assert shadow_main._ticker_cache_misses == 1
    snapshot = shadow_main._ticker_cache_snapshot()
    assert snapshot["entries"] == 1
    assert snapshot["fresh"] is True


def test_expired_ticker_cache_does_not_bypass_binance_guard():
    reset_ticker_cache()
    shadow_main._ticker_cache = (0.0, {"BTCUSDT": {"symbol": "BTCUSDT"}})
    shadow_main._binance_block_until = 10_000.0

    with patch.object(shadow_main.time, "time", return_value=20_000.0), patch.object(
        shadow_main, "_paper_original_24h_tickers", return_value={}
    ) as fetch:
        result = shadow_main._guarded_fetch_24h_tickers_with_cache()

    assert result == {}
    fetch.assert_called_once()
    assert shadow_main._ticker_cache_hits == 0
    assert shadow_main._ticker_cache_misses == 1


def test_ticker_cache_is_refreshed_after_expiry_when_binance_is_available():
    reset_ticker_cache()
    shadow_main._ticker_cache = (0.0, {"BTCUSDT": {"symbol": "BTCUSDT", "lastPrice": "79000"}})
    shadow_main._binance_block_until = 0.0
    fresh = {"BTCUSDT": {"symbol": "BTCUSDT", "lastPrice": "80000"}}

    with patch.object(shadow_main.time, "time", return_value=20_000.0), patch.object(
        shadow_main, "_paper_original_24h_tickers", return_value=fresh
    ) as fetch:
        result = shadow_main._guarded_fetch_24h_tickers_with_cache()
        snapshot = shadow_main._ticker_cache_snapshot()

    assert result == fresh
    fetch.assert_called_once()
    assert snapshot["entries"] == 1
    assert snapshot["fresh"] is True
    assert snapshot["age_seconds"] == 0.0
