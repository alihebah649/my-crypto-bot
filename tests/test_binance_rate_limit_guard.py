from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import requests

import shadow_main


def http_error(status: int, retry_after: str | None = None) -> requests.HTTPError:
    response = SimpleNamespace(status_code=status, headers={})
    if retry_after is not None:
        response.headers["Retry-After"] = retry_after
    error = requests.HTTPError(f"HTTP {status}")
    error.response = response
    return error


def reset_guard() -> None:
    shadow_main._binance_block_until = 0.0
    shadow_main._binance_backoff_seconds = 300.0
    shadow_main._binance_guard.update(
        {
            "state": "READY",
            "status_code": None,
            "blocked_until": 0.0,
            "retry_after_seconds": 0.0,
            "last_error": None,
            "last_path": None,
        }
    )
    with shadow_main._kline_cache_lock:
        shadow_main._kline_cache.clear()


def test_429_activates_guard_and_blocks_immediate_retry():
    reset_guard()
    calls = []

    def fail_once():
        calls.append("request")
        raise http_error(429, "17")

    with patch.object(shadow_main, "_original_fetch_24h_tickers", side_effect=fail_once):
        assert shadow_main._guarded_fetch_24h_tickers() == {}
        assert shadow_main._guarded_fetch_24h_tickers() == {}

    assert calls == ["request"]
    assert shadow_main._binance_guard["state"] == "BLOCKED"
    assert shadow_main._binance_guard["status_code"] == 429
    assert shadow_main._binance_guard["retry_after_seconds"] == 17.0
    assert shadow_main._market_data_guard_snapshot()["blocked"] is True


def test_418_uses_retry_after_and_increases_future_backoff():
    reset_guard()

    with patch.object(
        shadow_main,
        "_original_fetch_24h_tickers",
        side_effect=http_error(418, "120"),
    ):
        assert shadow_main._guarded_fetch_24h_tickers() == {}

    assert shadow_main._binance_guard["status_code"] == 418
    assert shadow_main._binance_guard["retry_after_seconds"] == 120.0
    assert shadow_main._binance_backoff_seconds >= 120.0


def test_guard_expires_and_allows_request_again():
    reset_guard()
    shadow_main._binance_block_until = 100.0
    shadow_main._binance_guard["state"] = "BLOCKED"

    with patch.object(shadow_main.time, "time", return_value=100.1):
        assert shadow_main._binance_guard_active() is False

    assert shadow_main._binance_guard["state"] == "READY"


def test_kline_429_blocks_follow_up_requests_without_hammering_binance():
    reset_guard()
    calls = []

    def fail_once(symbol, interval, limit):
        calls.append((symbol, interval, limit))
        raise http_error(429, "30")

    with patch.object(shadow_main, "_original_fetch_klines", side_effect=fail_once):
        assert shadow_main._guarded_fetch_klines("ADAUSDT", "5m", 60) == []
        assert shadow_main._guarded_fetch_klines("ADAUSDT", "5m", 60) == []

    assert calls == [("ADAUSDT", "5m", 60)]
    assert shadow_main._market_data_guard_snapshot()["blocked"] is True


def test_kline_cache_avoids_second_exchange_request_when_healthy():
    reset_guard()
    calls = []

    def succeed(symbol, interval, limit):
        calls.append((symbol, interval, limit))
        return [{"close": 1.0}]

    with patch.object(shadow_main, "_original_fetch_klines", side_effect=succeed):
        first = shadow_main._guarded_fetch_klines("ADAUSDT", "5m", 60)
        second = shadow_main._guarded_fetch_klines("ADAUSDT", "5m", 60)

    assert first == second == [{"close": 1.0}]
    assert calls == [("ADAUSDT", "5m", 60)]
