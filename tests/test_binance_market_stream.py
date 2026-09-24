from core.binance_market_stream import BinanceMarketStream


def test_stream_layout_stays_within_one_combined_connection():
    feed = BinanceMarketStream(["BTCUSDT", "ETHUSDT"])

    assert feed.stream_count == 10
    assert "btcusdt@kline_5m" in feed.stream_names
    assert "ethusdt@kline_4h" in feed.stream_names
    assert "btcusdt@ticker" in feed.stream_names
    assert feed.build_url().startswith("wss://stream.binance.com:9443/stream?streams=")


def test_shadow_feed_parses_kline_and_ticker_without_strategy_side_effects():
    feed = BinanceMarketStream(["BTCUSDT"])

    feed._consume_message(
        '{"stream":"btcusdt@kline_5m","data":'
        '{"e":"kline","E":1770000000000,"s":"BTCUSDT","k":'
        '{"t":1770000000000,"T":1770000299999,"s":"BTCUSDT","i":"5m",'
        '"o":"100.0","c":"101.0","h":"102.0","l":"99.0","v":"12.5",'
        '"q":"1262.5","x":true}}}'
    )
    feed._consume_message(
        '{"stream":"btcusdt@ticker","data":'
        '{"e":"24hrTicker","E":1770000001000,"s":"BTCUSDT",'
        '"c":"101.0","b":"100.9","a":"101.1","q":"2500000",'
        '"P":"1.2"}}'
    )

    kline = feed.get_latest_kline("BTCUSDT", "5m")
    ticker = feed.get_latest_ticker("BTCUSDT")

    assert kline["is_closed"] is True
    assert kline["close"] == 101.0
    assert kline["quote_volume"] == 1262.5
    assert ticker["lastPrice"] == 101.0
    assert ticker["bidPrice"] == 100.9
    assert ticker["askPrice"] == 101.1
    assert ticker["quoteVolume"] == 2500000.0

    snapshot = feed.snapshot()
    assert snapshot["mode"] == "SHADOW_ONLY"
    assert snapshot["kline_events"] == 1
    assert snapshot["ticker_events"] == 1
    assert snapshot["closed_kline_events"] == 1
    assert snapshot["symbols_with_latest_kline"] == 1
    assert snapshot["tickers_with_latest"] == 1
    assert snapshot["coverage_kline_percent"] == 6.25
    assert snapshot["coverage_ticker_percent"] == 100.0


def test_unknown_symbol_or_interval_does_not_expand_shadow_state():
    feed = BinanceMarketStream(["BTCUSDT"])

    feed._consume_message(
        '{"data":{"e":"kline","E":1,"s":"ETHUSDT","k":'
        '{"t":1,"T":2,"i":"5m","o":"1","c":"1","h":"1","l":"1","v":"1","q":"1","x":false}}}'
    )
    feed._consume_message(
        '{"data":{"e":"kline","E":1,"s":"BTCUSDT","k":'
        '{"t":1,"T":2,"i":"1m","o":"1","c":"1","h":"1","l":"1","v":"1","q":"1","x":false}}}'
    )

    assert feed.get_latest_kline("ETHUSDT", "5m") is None
    assert feed.get_latest_kline("BTCUSDT", "1m") is None
    assert feed.snapshot()["symbols_with_latest_kline"] == 0
