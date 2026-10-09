from __future__ import annotations

import json

from core.okx_market_stream import OKXMarketStream


def test_okx_stream_consumes_spot_ticker_snapshot():
    stream = OKXMarketStream(["BTCUSDT"])
    stream._consume_message(json.dumps({
        "arg": {"channel": "tickers", "instId": "BTC-USDT"},
        "data": [{
            "instId": "BTC-USDT",
            "last": "60000",
            "bidPx": "59999",
            "askPx": "60001",
            "open24h": "59000",
            "vol24h": "12.5",
            "volCcy24h": "750000",
            "high24h": "61000",
            "low24h": "58000",
        }],
        "ts": "1791500000000",
    }))

    ticker = stream.get_latest_ticker("BTCUSDT")
    assert ticker is not None
    assert ticker["lastPrice"] == 60000.0
    assert ticker["bidPrice"] == 59999.0
    assert ticker["askPrice"] == 60001.0
    assert ticker["quoteVolume"] == 750000.0
    assert ticker["market_data_source"] == "OKX"
    assert ticker["market_data_transport"] == "WEBSOCKET"
    snapshot = stream.snapshot()
    assert snapshot["tickers_with_latest"] == 1
    assert snapshot["ticker_events"] == 1


def test_okx_stream_consumes_closed_candle_and_updates_history():
    stream = OKXMarketStream(["BTCUSDT"], intervals=("5m",))
    stream._consume_message(json.dumps({
        "arg": {"channel": "candle5m", "instId": "BTC-USDT"},
        "data": [["300000", "3.0", "3.2", "2.9", "3.1", "30", "93", "93.5", "1"]],
        "ts": "1791500000000",
    }))

    rows = stream.get_kline_history("BTCUSDT", "5m", 60)
    assert len(rows) == 1
    assert rows[0]["open_time"] == 300000
    assert rows[0]["close_time"] == 599999
    assert rows[0]["close"] == 3.1
    assert rows[0]["quote_volume"] == 93.5
    assert rows[0]["is_closed"] is True
    assert rows[0]["market_data_source"] == "OKX"
    assert rows[0]["market_data_transport"] == "WEBSOCKET"
    assert stream.get_latest_closed_kline("BTCUSDT", "5m")["open_time"] == 300000


def test_okx_stream_keeps_live_candle_out_of_closed_candle_slot():
    stream = OKXMarketStream(["BTCUSDT"], intervals=("5m",))
    stream._consume_message(json.dumps({
        "arg": {"channel": "candle5m", "instId": "BTC-USDT"},
        "data": [["300000", "3.0", "3.2", "2.9", "3.1", "30", "93", "93.5", "0"]],
    }))

    assert stream.get_latest_kline("BTCUSDT", "5m")["is_closed"] is False
    assert stream.get_latest_closed_kline("BTCUSDT", "5m") is None


def test_okx_subscriptions_are_batched_and_use_spot_instrument_ids():
    symbols = [f"COIN{i}USDT" for i in range(22)]
    stream = OKXMarketStream(symbols, intervals=("5m", "15m", "1h", "4h"))

    batches = stream.subscription_batches
    flattened = [arg for batch in batches for arg in batch]
    assert len(stream.subscription_args) == 110
    assert len(stream.ticker_subscription_args) == 22
    assert len(stream.candle_subscription_args) == 88
    assert [len(batch) for batch in batches] == [40, 40, 30]
    assert all(len(batch) <= 40 for batch in batches)
    assert flattened[0] == {"channel": "tickers", "instId": "COIN0-USDT"}
    assert {"channel": "candle5m", "instId": "COIN0-USDT"} in flattened
    assert {"channel": "candle1H", "instId": "COIN0-USDT"} in flattened


def test_okx_stream_reports_subscription_and_parse_health():
    stream = OKXMarketStream(["BTCUSDT"], intervals=("5m",))
    initial = stream.snapshot(now=1000.0)
    assert initial["mode"] == "PAPER_VENUE_LAB_OKX_WS"
    assert initial["public_url"].endswith("/ws/v5/public")
    assert initial["business_url"].endswith("/ws/v5/business")
    assert initial["public_connected"] is False
    assert initial["business_connected"] is False
    assert initial["expected_tickers"] == 1
    assert initial["expected_kline_streams"] == 1
    assert initial["event_stream_healthy"] is False

    stream._consume_message('not-json')
    assert stream.snapshot()["parse_errors"] == 1


def test_okx_health_requires_both_public_and_business_connections():
    stream = OKXMarketStream(["BTCUSDT"], intervals=("5m",))
    stream._set_connection_state("public", True)
    assert stream.snapshot()["connected"] is False
    stream._set_connection_state("business", True)
    assert stream.snapshot()["connected"] is True
