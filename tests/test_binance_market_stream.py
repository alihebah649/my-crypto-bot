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


def test_runtime_kline_adapter_hydrates_from_manager_cache_before_rest():
    import sys
    import types
    from types import SimpleNamespace

    symbols = ["BTCUSDT"]
    calls = []

    def fake_kline_fetch(symbol, interval, limit):
        calls.append((symbol, interval, limit))
        return []

    class FakeCache:
        def get(self, key):
            if key == "5m:BTCUSDT:3":
                return SimpleNamespace(
                    payload=[
                        {"open_time": 1000, "open": 100, "high": 101, "low": 99, "close": 100.5, "volume": 10},
                        {"open_time": 2000, "open": 100.5, "high": 102, "low": 100, "close": 101.5, "volume": 12},
                        {"open_time": 3000, "open": 101.5, "high": 103, "low": 101, "close": 102.5, "volume": 14},
                    ]
                )
            return None

        def put(self, key, payload, fetched_at=None):
            return None

    fake_legacy = types.ModuleType("shadow_main_legacy")
    fake_legacy.fetch_24h_tickers = lambda requested: {}
    fake_legacy.fetch_klines = fake_kline_fetch
    fake_legacy.fetch_strategy_data = lambda: None
    fake_legacy._BINANCE_MARKET_DATA_SYMBOL_SET = {"BTCUSDT"}
    fake_legacy._BYBIT_MARKET_DATA_SYMBOL_SET = set()
    fake_legacy._market_data_kline_refresh_symbols = {"BTCUSDT"}
    fake_legacy._binance_ws_market_data_integration_installed = False
    fake_legacy.market_data_manager = SimpleNamespace(cache=FakeCache())

    previous_legacy = sys.modules.get("shadow_main_legacy")
    try:
        sys.modules["shadow_main_legacy"] = fake_legacy
        feed = BinanceMarketStream(symbols)
        feed._install_runtime_integration()

        rows = fake_legacy.fetch_klines("BTCUSDT", "5m", 3)

        assert len(calls) == 0
        assert [row["open_time"] for row in rows] == [1000, 2000, 3000]
        assert feed.snapshot()["runtime_integration"]["kline_manager_cache_seeds"] == 1
    finally:
        if previous_legacy is None:
            sys.modules.pop("shadow_main_legacy", None)
        else:
            sys.modules["shadow_main_legacy"] = previous_legacy


def test_runtime_kline_adapter_uses_rest_only_for_cold_start_seed():
    import sys
    import types

    symbols = ["BTCUSDT"]
    calls = []

    def fake_ticker_fetch(requested):
        return {
            symbol: {
                "symbol": symbol,
                "lastPrice": 100.0,
                "market_data_source": "BINANCE",
            }
            for symbol in requested
        }

    def fake_kline_fetch(symbol, interval, limit):
        calls.append((symbol, interval, limit))
        return [
            {"open_time": 1000, "open": 100, "high": 101, "low": 99, "close": 100.5, "volume": 10},
            {"open_time": 2000, "open": 100.5, "high": 102, "low": 100, "close": 101.5, "volume": 12},
            {"open_time": 3000, "open": 101.5, "high": 103, "low": 101, "close": 102.5, "volume": 14},
        ]

    fake_legacy = types.ModuleType("shadow_main_legacy")
    fake_legacy.fetch_24h_tickers = fake_ticker_fetch
    fake_legacy.fetch_klines = fake_kline_fetch
    fake_legacy.fetch_strategy_data = lambda: None
    fake_legacy._BINANCE_MARKET_DATA_SYMBOL_SET = {"BTCUSDT"}
    fake_legacy._BYBIT_MARKET_DATA_SYMBOL_SET = set()
    fake_legacy._market_data_kline_refresh_symbols = None
    fake_legacy._binance_ws_market_data_integration_installed = False

    previous_legacy = sys.modules.get("shadow_main_legacy")
    try:
        sys.modules["shadow_main_legacy"] = fake_legacy

        feed = BinanceMarketStream(symbols)
        feed._install_runtime_integration()

        first = fake_legacy.fetch_klines("BTCUSDT", "5m", 3)
        assert len(calls) == 1
        assert [row["open_time"] for row in first] == [1000, 2000, 3000]
        assert feed.snapshot()["runtime_integration"]["kline_rest_seeds"] == 1

        feed._consume_message(
            '{"data":{"e":"kline","E":3,"s":"BTCUSDT","k":'
            '{"t":4000,"T":4299999,"s":"BTCUSDT","i":"5m",'
            '"o":"102.5","c":"103","h":"104","l":"102","v":"4","q":"412","x":false}}}'
        )
        second = fake_legacy.fetch_klines("BTCUSDT", "5m", 3)

        assert len(calls) == 1
        assert [row["open_time"] for row in second] == [2000, 3000, 4000]
        assert second[-1]["close"] == 103.0
    finally:
        if previous_legacy is None:
            sys.modules.pop("shadow_main_legacy", None)
        else:
            sys.modules["shadow_main_legacy"] = previous_legacy


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


def test_runtime_kline_cache_writes_are_coalesced(tmp_path):
    import sys
    import time
    import types

    flushes = []
    puts = []

    class FakeCache:
        def put(self, key, payload, fetched_at=None, persist=True):
            puts.append((key, len(payload), persist))

        def flush(self):
            flushes.append(time.time())

    fake_legacy = types.ModuleType("shadow_main_legacy")
    fake_legacy.market_data_manager = types.SimpleNamespace(cache=FakeCache())

    previous_legacy = sys.modules.get("shadow_main_legacy")
    try:
        sys.modules["shadow_main_legacy"] = fake_legacy
        feed = BinanceMarketStream(["BTCUSDT"])
        feed._runtime_kline_history[("BTCUSDT", "5m")] = [
            {
                "open_time": index,
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.0,
                "volume": 1.0,
            }
            for index in range(60)
        ]

        feed._persist_runtime_kline_to_manager_cache("BTCUSDT", "5m")
        feed._runtime_kline_history[("BTCUSDT", "5m")][-1]["close"] = 101.0
        feed._persist_runtime_kline_to_manager_cache("BTCUSDT", "5m")

        assert [item[2] for item in puts] == [False, False]
        assert len(flushes) == 1
        assert feed.snapshot()["runtime_integration"]["kline_manager_cache_writes"] == 2
        assert feed.snapshot()["runtime_integration"]["kline_manager_cache_flushes"] == 1
    finally:
        if previous_legacy is None:
            sys.modules.pop("shadow_main_legacy", None)
        else:
            sys.modules["shadow_main_legacy"] = previous_legacy


def test_runtime_kline_history_uses_strategy_required_depth():
    feed = BinanceMarketStream(["BTCUSDT"])

    feed._seed_runtime_kline_history(
        "BTCUSDT",
        "5m",
        [{"open_time": index, "close": 100.0} for index in range(100)],
        required_limit=60,
    )
    feed._seed_runtime_kline_history(
        "BTCUSDT",
        "15m",
        [{"open_time": index, "close": 100.0} for index in range(200)],
        required_limit=150,
    )

    assert len(feed._runtime_kline_history[("BTCUSDT", "5m")]) == 60
    assert len(feed._runtime_kline_history[("BTCUSDT", "15m")]) == 150


def test_custom_paper_stream_keeps_only_5m_and_15m_high_frequency_intervals():
    feed = BinanceMarketStream(["BTCUSDT", "ETHUSDT"], intervals=("5m", "15m"))

    assert feed.stream_count == 6
    assert "btcusdt@kline_5m" in feed.stream_names
    assert "btcusdt@kline_15m" in feed.stream_names
    assert "btcusdt@kline_1h" not in feed.stream_names
    assert "btcusdt@kline_4h" not in feed.stream_names
    assert "ethusdt@ticker" in feed.stream_names
