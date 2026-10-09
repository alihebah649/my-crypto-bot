from __future__ import annotations

from unittest.mock import patch

import pytest
import requests

from core.okx_market_data import (
    OKXMarketDataClient,
    OKXMarketDataError,
    from_okx_inst_id,
    to_okx_inst_id,
)


class FakeResponse:
    def __init__(self, payload, status_code=200, text=""):
        self._payload = payload
        self.status_code = status_code
        self.text = text or str(payload)

    def json(self):
        return self._payload


def test_okx_symbol_conversion_handles_bot_symbols_and_instrument_ids():
    assert to_okx_inst_id("BTCUSDT") == "BTC-USDT"
    assert to_okx_inst_id("ETH-USDT") == "ETH-USDT"
    assert from_okx_inst_id("BTC-USDT") == "BTCUSDT"
    with pytest.raises(ValueError):
        to_okx_inst_id("BTCUSD")


def test_okx_ticker_normalization_uses_public_spot_endpoint(monkeypatch):
    calls = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        calls.update({"url": url, "params": params, "headers": headers, "timeout": timeout})
        return FakeResponse({
            "code": "0",
            "msg": "",
            "data": [
                {
                    "instId": "BTC-USDT",
                    "last": "60000",
                    "bidPx": "59999",
                    "askPx": "60001",
                    "open24h": "59000",
                    "vol24h": "12.5",
                    "volCcy24h": "750000",
                    "high24h": "61000",
                    "low24h": "58000",
                    "ts": "1791500000000",
                },
                {
                    "instId": "ETH-USDT",
                    "last": "3000",
                    "bidPx": "2999",
                    "askPx": "3001",
                    "open24h": "3000",
                },
            ],
        })

    monkeypatch.setattr(requests, "get", fake_get)
    result = OKXMarketDataClient().fetch_tickers(["BTCUSDT"])

    assert calls["url"].endswith("/api/v5/market/tickers")
    assert calls["params"] == {"instType": "SPOT"}
    assert result.keys() == {"BTCUSDT"}
    assert result["BTCUSDT"]["lastPrice"] == 60000.0
    assert result["BTCUSDT"]["bidPrice"] == 59999.0
    assert result["BTCUSDT"]["askPrice"] == 60001.0
    assert result["BTCUSDT"]["volume"] == 12.5
    assert result["BTCUSDT"]["quoteVolume"] == 750000.0
    assert result["BTCUSDT"]["priceChangePercent"] == pytest.approx((60000 / 59000 - 1) * 100)
    assert result["BTCUSDT"]["market_data_source"] == "OKX"


def test_okx_kline_normalization_sorts_rows_and_derives_close_time(monkeypatch):
    calls = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        calls.update({"url": url, "params": params})
        return FakeResponse({
            "code": "0",
            "msg": "",
            "data": [
                ["300000", "3.0", "3.2", "2.9", "3.1", "30", "93", "93.5", "1"],
                ["0", "1.0", "1.2", "0.9", "1.1", "10", "11", "11.5", "1"],
            ],
        })

    monkeypatch.setattr(requests, "get", fake_get)
    candles = OKXMarketDataClient().fetch_klines("BTCUSDT", "5m", 2)

    assert calls["url"].endswith("/api/v5/market/candles")
    assert calls["params"] == {"instId": "BTC-USDT", "bar": "5m", "limit": "2"}
    assert [row["open_time"] for row in candles] == [0, 300000]
    assert candles[0]["close_time"] == 299999
    assert candles[0]["close"] == 1.1
    assert candles[0]["quote_volume"] == 11.5
    assert candles[0]["is_closed"] is True
    assert candles[0]["market_data_source"] == "OKX"
    assert candles[0]["market_data_transport"] == "REST_COLD_START"


def test_okx_rate_limit_is_reported_as_market_data_error(monkeypatch):
    def fake_get(*args, **kwargs):
        return FakeResponse({"code": "50011", "msg": "Rate limit reached"}, status_code=429)

    monkeypatch.setattr(requests, "get", fake_get)
    with pytest.raises(OKXMarketDataError, match="HTTP 429"):
        OKXMarketDataClient().fetch_tickers(["BTCUSDT"])


def test_okx_api_business_error_is_not_accepted_as_market_data(monkeypatch):
    def fake_get(*args, **kwargs):
        return FakeResponse({"code": "51000", "msg": "Parameter error", "data": []})

    monkeypatch.setattr(requests, "get", fake_get)
    with pytest.raises(OKXMarketDataError, match="API error"):
        OKXMarketDataClient().fetch_tickers(["BTCUSDT"])


def test_okx_lab_ticker_router_uses_only_its_own_stream(monkeypatch):
    import time
    import shadow_main

    class FakeStream:
        stale_after_seconds = 30.0

        def get_latest_ticker(self, symbol):
            return {
                "symbol": symbol,
                "lastPrice": 42.0,
                "received_at": time.time(),
                "market_data_source": "OKX",
            }

    monkeypatch.setattr(shadow_main, "PAPER_VENUE_MODE", "OKX_ONLY_LAB")
    monkeypatch.setattr(shadow_main, "_okx_market_stream", FakeStream())
    monkeypatch.setattr(
        shadow_main,
        "_original_fetch_24h_tickers",
        lambda symbols: (_ for _ in ()).throw(AssertionError("Binance REST must not be called")),
    )
    monkeypatch.setattr(
        shadow_main._okx_client,
        "fetch_tickers",
        lambda symbols: (_ for _ in ()).throw(AssertionError("REST fallback not needed for fresh WS data")),
    )

    result = shadow_main._guarded_fetch_24h_tickers(["BTCUSDT"])

    assert set(result) == {"BTCUSDT"}
    assert result["BTCUSDT"]["market_data_source"] == "OKX"


def test_okx_lab_health_uses_okx_guard_not_healthy_binance_guard(monkeypatch):
    import time
    import shadow_main

    monkeypatch.setattr(shadow_main, "PAPER_VENUE_MODE", "OKX_ONLY_LAB")
    monkeypatch.setattr(shadow_main, "_binance_guard", {"state": "READY", "last_error": None})
    monkeypatch.setattr(shadow_main, "_OKX_GUARD", {
        "state": "BLOCKED", "status_code": 429, "last_error": "rate limited",
        "blocked_until": time.time() + 120, "retry_after_seconds": 120,
        "last_path": "/api/v5/market/candles",
    })
    monkeypatch.setattr(shadow_main, "_OKX_BLOCK_UNTIL", time.time() + 120)

    snapshot = shadow_main._market_data_guard_snapshot()

    assert snapshot["venue_mode"] == "OKX_ONLY_LAB"
    assert snapshot["state"] == "BLOCKED"
    assert snapshot["status_code"] == 429
    assert snapshot["blocked"] is True
    assert snapshot["okx"]["state"] == "BLOCKED"


def test_isolated_okx_lab_rejects_persisted_candles_from_binance_or_unknown_source(monkeypatch):
    import shadow_main

    monkeypatch.setattr(shadow_main, "PAPER_VENUE_MODE", "OKX_ONLY_LAB")

    assert shadow_main._lab_kline_payload_matches_venue([
        {"market_data_source": "OKX", "open_time": 1000, "close": 1.0},
        {"market_data_source": "OKX", "open_time": 2000, "close": 1.1},
    ]) is True
    assert shadow_main._lab_kline_payload_matches_venue([
        {"market_data_source": "BINANCE", "open_time": 1000, "close": 1.0},
    ]) is False
    assert shadow_main._lab_kline_payload_matches_venue([
        {"open_time": 1000, "close": 1.0},
    ]) is False


def test_selected_venue_websocket_health_reports_both_okx_connections(monkeypatch):
    import shadow_main

    class FakeStream:
        def snapshot(self):
            return {
                "available": True,
                "mode": "PAPER_VENUE_LAB_OKX_WS",
                "connected": True,
                "public_connected": True,
                "business_connected": False,
                "event_stream_healthy": False,
                "stream_count": 110,
                "expected_kline_streams": 88,
                "symbols_with_latest_kline": 88,
                "expected_tickers": 22,
                "tickers_with_latest": 22,
                "events_total": 1500,
                "closed_kline_events": 88,
                "reconnects": 0,
                "parse_errors": 0,
                "last_event_age_seconds": 0.2,
                "last_error": None,
            }

    monkeypatch.setattr(shadow_main, "PAPER_VENUE_MODE", "OKX_ONLY_LAB")
    monkeypatch.setattr(shadow_main, "_okx_market_stream", FakeStream())
    monkeypatch.setattr(
        shadow_main,
        "_binance_market_stream",
        type("WrongVenue", (), {"snapshot": lambda self: (_ for _ in ()).throw(AssertionError("wrong venue"))})(),
    )

    venue, snapshot = shadow_main._selected_venue_websocket_snapshot()

    assert venue == "OKX"
    assert snapshot["public_connected"] is True
    assert snapshot["business_connected"] is False
    assert snapshot["event_stream_healthy"] is False


def test_selected_venue_websocket_health_never_falls_back_to_binance_in_okx_mode(monkeypatch):
    import shadow_main

    monkeypatch.setattr(shadow_main, "PAPER_VENUE_MODE", "OKX_ONLY_LAB")
    monkeypatch.setattr(shadow_main, "_okx_market_stream", None)
    monkeypatch.setattr(
        shadow_main,
        "_binance_market_stream",
        type("WrongVenue", (), {"snapshot": lambda self: {"connected": True, "event_stream_healthy": True}})(),
    )

    venue, snapshot = shadow_main._selected_venue_websocket_snapshot()

    assert venue == "OKX"
    assert snapshot["available"] is False
    assert snapshot["connected"] is False
    assert snapshot["reason"] == "SELECTED_VENUE_STREAM_UNAVAILABLE"
