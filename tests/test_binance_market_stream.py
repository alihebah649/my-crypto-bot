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
    assert snapshot["mode"] == "PAPER_AUTHORITATIVE_BINANCE_WS"
    assert snapshot["kline_events"] == 1
    assert snapshot["ticker_events"] == 1
    assert snapshot["closed_kline_events"] == 1
    assert snapshot["symbols_with_latest_kline"] == 1
    assert snapshot["tickers_with_latest"] == 1
    assert snapshot["coverage_kline_percent"] == 25.0
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


def test_latest_closed_kline_survives_start_of_next_candle():
    feed = BinanceMarketStream(["BTCUSDT"])

    feed._consume_message(
        '{"data":{"e":"kline","E":1,"s":"BTCUSDT","k":'
        '{"t":1000,"T":1299999,"s":"BTCUSDT","i":"5m",'
        '"o":"100","c":"101","h":"102","l":"99","v":"10","q":"1005","x":true}}}'
    )
    feed._consume_message(
        '{"data":{"e":"kline","E":2,"s":"BTCUSDT","k":'
        '{"t":1300000,"T":1599999,"s":"BTCUSDT","i":"5m",'
        '"o":"101","c":"101.5","h":"102","l":"100.5","v":"2","q":"203","x":false}}}'
    )

    latest = feed.get_latest_kline("BTCUSDT", "5m")
    latest_closed = feed.get_latest_closed_kline("BTCUSDT", "5m")

    assert latest["is_closed"] is False
    assert latest["open_time"] == 1300000
    assert latest_closed["is_closed"] is True
    assert latest_closed["open_time"] == 1000
    assert latest_closed["close"] == 101.0


def test_runtime_ticker_adapter_routes_complementary_bybit_lane_when_legacy_set_is_absent():
    import shadow_main_legacy as legacy

    symbols = [
        "BTCUSDT",
        "ETHUSDT",
        "SOLUSDT",
        "LINKUSDT",
    ]
    binance_symbols = set(symbols[:2])
    bybit_symbols = set(symbols[2:])

    original_fetch = legacy.fetch_24h_tickers
    original_kline_fetch = legacy.fetch_klines
    original_flag = getattr(
        legacy, "_binance_ws_market_data_integration_installed", None
    )
    legacy_bybit_attr = getattr(
        legacy, "_BYBIT_MARKET_DATA_SYMBOL_SET", None
    )
    had_bybit_attr = hasattr(legacy, "_BYBIT_MARKET_DATA_SYMBOL_SET")

    def fake_ticker_fetch(requested):
        requested = list(requested)
        return {
            symbol: {
                "symbol": symbol,
                "lastPrice": 200.0,
                "market_data_source": "BYBIT",
            }
            for symbol in requested
        }

    def fake_kline_fetch(symbol, interval, limit):
        return []

    try:
        legacy.fetch_24h_tickers = fake_ticker_fetch
        legacy.fetch_klines = fake_kline_fetch
        legacy._binance_ws_market_data_integration_installed = False
        if had_bybit_attr:
            del legacy._BYBIT_MARKET_DATA_SYMBOL_SET

        feed = BinanceMarketStream(symbols)

        def fresh_ticker(symbol):
            if symbol in binance_symbols:
                return {
                    "symbol": symbol,
                    "lastPrice": 100.0,
                    "market_data_source": "BINANCE",
                    "market_data_transport": "WEBSOCKET",
                }
            return None

        feed._fresh_ticker = fresh_ticker
        feed._install_runtime_integration()

        routed = legacy.fetch_24h_tickers(symbols)

        assert set(routed) == set(symbols)
        assert all(routed[s]["market_data_source"] == "BINANCE" for s in binance_symbols)
        assert all(routed[s]["market_data_source"] == "BYBIT" for s in bybit_symbols)
    finally:
        legacy.fetch_24h_tickers = original_fetch
        legacy.fetch_klines = original_kline_fetch
        if original_flag is None:
            legacy.__dict__.pop("_binance_ws_market_data_integration_installed", None)
        else:
            legacy._binance_ws_market_data_integration_installed = original_flag
        if had_bybit_attr:
            legacy._BYBIT_MARKET_DATA_SYMBOL_SET = legacy_bybit_attr
        else:
            legacy.__dict__.pop("_BYBIT_MARKET_DATA_SYMBOL_SET", None)
