from __future__ import annotations

import json

from core.bybit_market_stream import BybitMarketStream


def test_bybit_stream_consumes_spot_ticker_snapshot():
    stream = BybitMarketStream(["FETUSDT"])
    stream._consume_message(
        json.dumps(
            {
                "topic": "tickers.FETUSDT",
                "type": "snapshot",
                "ts": 1234567890,
                "data": {
                    "symbol": "FETUSDT",
                    "lastPrice": "0.2382",
                    "bid1Price": "0.2380",
                    "ask1Price": "0.2383",
                    "price24hPcnt": "0.0125",
                    "turnover24h": "12345.6",
                    "volume24h": "50000",
                },
            }
        )
    )

    ticker = stream.get_latest_ticker("FETUSDT")
    assert ticker is not None
    assert ticker["lastPrice"] == 0.2382
    assert ticker["bidPrice"] == 0.2380
    assert ticker["askPrice"] == 0.2383
    assert ticker["priceChangePercent"] == 1.25
    assert ticker["market_data_source"] == "BYBIT"


def test_bybit_stream_consumes_kline_snapshot_and_confirm():
    stream = BybitMarketStream(["FETUSDT"], intervals=("5m",))
    stream._consume_message(
        json.dumps(
            {
                "topic": "kline.5.FETUSDT",
                "type": "snapshot",
                "ts": 1234567890,
                "data": [
                    {
                        "start": 100000,
                        "end": 399999,
                        "interval": "5",
                        "open": "1.0",
                        "close": "1.1",
                        "high": "1.2",
                        "low": "0.9",
                        "volume": "10",
                        "turnover": "10.5",
                        "confirm": True,
                        "timestamp": 399999,
                    }
                ],
            }
        )
    )

    rows = stream.get_kline_history("FETUSDT", "5m", 60)
    assert len(rows) == 1
    assert rows[0]["open_time"] == 100000
    assert rows[0]["close_time"] == 399999
    assert rows[0]["close"] == 1.1
    assert rows[0]["is_closed"] is True
    assert stream.get_latest_closed_kline("FETUSDT", "5m")["open_time"] == 100000


def test_bybit_stream_seeded_rest_history_is_exposed_to_runtime():
    stream = BybitMarketStream(["FETUSDT"], intervals=("5m",))
    seeded = stream.seed_kline_history(
        "FETUSDT",
        "5m",
        [
            {
                "open_time": i * 300000,
                "close_time": i * 300000 + 299999,
                "open": 1.0,
                "high": 1.1,
                "low": 0.9,
                "close": 1.05,
                "volume": 10.0,
                "market_data_source": "BYBIT",
                "market_data_transport": "REST_COLD_START",
            }
            for i in range(1, 61)
        ],
    )

    assert seeded == 60
    rows = stream.get_kline_history("FETUSDT", "5m", 60)
    assert len(rows) == 60
    assert rows[-1]["market_data_transport"] == "REST_COLD_START"
