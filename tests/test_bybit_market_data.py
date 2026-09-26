from __future__ import annotations

from unittest.mock import patch

import pytest
import requests

from core.bybit_market_data import BybitMarketDataClient, BybitMarketDataError


class FakeResponse:
    def __init__(self, payload, status_code=200, text=""):
        self._payload = payload
        self.status_code = status_code
        self.text = text or str(payload)

    def json(self):
        return self._payload


def test_bybit_ticker_normalization(monkeypatch):
    calls = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        calls.update({"url": url, "params": params, "headers": headers, "timeout": timeout})
        return FakeResponse(
            {
                "retCode": 0,
                "retMsg": "OK",
                "result": {
                    "category": "spot",
                    "list": [
                        {
                            "symbol": "FETUSDT",
                            "bid1Price": "0.2380",
                            "ask1Price": "0.2383",
                            "lastPrice": "0.2382",
                            "price24hPcnt": "0.0125",
                            "turnover24h": "12345.6",
                            "volume24h": "50000",
                            "highPrice24h": "0.25",
                            "lowPrice24h": "0.22",
                        }
                    ],
                },
            }
        )

    monkeypatch.setattr(requests, "get", fake_get)
    result = BybitMarketDataClient().fetch_tickers(["FETUSDT"])

    assert calls["url"].endswith("/v5/market/tickers")
    assert calls["params"] == {"category": "spot"}
    assert result["FETUSDT"]["lastPrice"] == 0.2382
    assert result["FETUSDT"]["bidPrice"] == 0.238
    assert result["FETUSDT"]["askPrice"] == 0.2383
    assert result["FETUSDT"]["quoteVolume"] == 12345.6
    assert result["FETUSDT"]["priceChangePercent"] == 1.25
    assert result["FETUSDT"]["market_data_source"] == "BYBIT"


def test_bybit_kline_normalization_reverses_response_and_derives_close_time(monkeypatch):
    rows = [
        ["300000", "3", "3.2", "2.9", "3.1", "30", "unused"],
        ["0", "1", "1.2", "0.9", "1.1", "10", "unused"],
    ]

    def fake_get(url, params=None, headers=None, timeout=None):
        assert url.endswith("/v5/market/kline")
        assert params == {
            "category": "spot",
            "symbol": "FETUSDT",
            "interval": "5",
            "limit": 2,
        }
        return FakeResponse({"retCode": 0, "retMsg": "OK", "result": {"list": rows}})

    monkeypatch.setattr(requests, "get", fake_get)
    candles = BybitMarketDataClient().fetch_klines("FETUSDT", "5m", 2)

    assert [c["open_time"] for c in candles] == [0, 300000]
    assert candles[0]["close"] == 1.1
    assert candles[0]["close_time"] == 299999
    assert candles[1]["volume"] == 30.0


def test_bybit_rate_limit_raises_market_data_error(monkeypatch):
    def fake_get(*args, **kwargs):
        return FakeResponse({"retCode": 0}, status_code=403, text="access too frequent")

    monkeypatch.setattr(requests, "get", fake_get)
    with pytest.raises(BybitMarketDataError):
        BybitMarketDataClient().fetch_tickers(["FETUSDT"])


def test_paper_market_data_symbols_are_split_evenly_between_venues():
    import shadow_main

    assert len(shadow_main.TRADING_SYMBOLS) == 22
    assert len(shadow_main._BINANCE_MARKET_DATA_SYMBOLS) == 11
    assert len(shadow_main._BYBIT_MARKET_DATA_SYMBOLS) == 11
    assert set(shadow_main._BINANCE_MARKET_DATA_SYMBOLS).isdisjoint(
        shadow_main._BYBIT_MARKET_DATA_SYMBOLS
    )


def test_ticker_router_does_not_send_bybit_symbols_to_binance():
    import shadow_main

    binance_calls = []
    bybit_calls = []
    original_bybit_cache = shadow_main._BYBIT_TICKER_CACHE
    try:
        shadow_main._BYBIT_TICKER_CACHE = None

        def fake_binance(symbols):
            binance_calls.append(list(symbols))
            return {s: {"symbol": s, "lastPrice": 100.0} for s in symbols}

        def fake_bybit(symbols):
            bybit_calls.append(list(symbols))
            return {
                s: {"symbol": s, "lastPrice": 200.0, "market_data_source": "BYBIT"}
                for s in symbols
            }

        with patch.object(shadow_main, "_original_fetch_24h_tickers", side_effect=fake_binance),              patch.object(shadow_main._bybit_client, "fetch_tickers", side_effect=fake_bybit):
            result = shadow_main._guarded_fetch_24h_tickers()

        assert len(binance_calls) == 1
        assert set(binance_calls[0]) == set(shadow_main._BINANCE_MARKET_DATA_SYMBOLS)
        assert len(bybit_calls) == 1
        assert set(bybit_calls[0]) == set(shadow_main._BYBIT_MARKET_DATA_SYMBOLS)
        assert all(result[s]["market_data_source"] == "BINANCE" for s in shadow_main._BINANCE_MARKET_DATA_SYMBOLS)
        assert all(result[s]["market_data_source"] == "BYBIT" for s in shadow_main._BYBIT_MARKET_DATA_SYMBOLS)
    finally:
        shadow_main._BYBIT_TICKER_CACHE = original_bybit_cache
