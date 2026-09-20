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


def test_binance_metrics_exposes_own_traffic_separately_from_ip_wide_weight():
    import sitecustomize

    now = 10_000.0
    with sitecustomize._BINANCE_METRICS_LOCK:
        old_events = list(sitecustomize._BINANCE_METRICS_EVENTS)
        old_last_weight = sitecustomize._BINANCE_METRICS_LAST_WEIGHT_1M
        sitecustomize._BINANCE_METRICS_EVENTS.clear()
        sitecustomize._BINANCE_METRICS_EVENTS.append({
            "at": now - 10.0,
            "path": "/api/v3/ticker/24hr",
            "synthetic": False,
        })
        sitecustomize._BINANCE_METRICS_EVENTS.append({
            "at": now - 5.0,
            "path": "/api/v3/klines",
            "synthetic": False,
        })
        sitecustomize._BINANCE_METRICS_EVENTS.append({
            "at": now - 4.0,
            "path": "/api/v3/ticker/24hr",
            "synthetic": True,
        })
        sitecustomize._BINANCE_METRICS_LAST_WEIGHT_1M = 6120
    try:
        rolling = sitecustomize._rolling_binance_request_diagnostics(now)
        assert rolling["own_real_requests"] == 2
        assert rolling["own_requests_by_path"] == {
            "/api/v3/ticker/24hr": 1,
            "/api/v3/klines": 1,
        }
        assert rolling["own_estimated_known_weight"] == 4
        assert rolling["last_observed_ip_weight_1m"] == 6120
        assert rolling["ip_weight_over_limit"] is True
    finally:
        with sitecustomize._BINANCE_METRICS_LOCK:
            sitecustomize._BINANCE_METRICS_EVENTS.clear()
            sitecustomize._BINANCE_METRICS_EVENTS.extend(old_events)
            sitecustomize._BINANCE_METRICS_LAST_WEIGHT_1M = old_last_weight


def test_paper_market_data_uses_dedicated_public_market_data_endpoint(monkeypatch):
    import shadow_main_legacy

    captured = {}

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"ok": True}

    def fake_get(url, params=None, headers=None, timeout=None):
        captured.update({"url": url, "params": params, "headers": headers, "timeout": timeout})
        return _Response()

    monkeypatch.setattr(shadow_main_legacy.requests, "get", fake_get)
    shadow_main_legacy.BINANCE_MARKET_DATA_REST = "https://data-api.binance.vision"
    assert shadow_main_legacy._binance_get("/api/v3/klines", {"symbol": "BTCUSDT"}) == {"ok": True}
    assert captured["url"] == "https://data-api.binance.vision/api/v3/klines"
    assert captured["url"] != "https://api.binance.com/api/v3/klines"
