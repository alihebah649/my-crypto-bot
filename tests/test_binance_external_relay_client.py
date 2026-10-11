from __future__ import annotations

import json
import sys
import time
import types

from core.binance_market_stream import BinanceMarketStream


def _relay_snapshot(symbols=("BTCUSDT",), *, stale_ticker_seconds=0, rows_by_interval=None):
    now_ms = int(time.time() * 1000)
    generated_ms = now_ms - 120_000
    rows_by_interval = rows_by_interval or {"5m": 60, "15m": 150, "1h": 60, "4h": 60}
    payload_symbols = {}
    steps = {"5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000}
    for symbol in symbols:
        klines = {}
        for interval, limit in rows_by_interval.items():
            rows = []
            step = steps[interval]
            for index in range(limit):
                open_time = generated_ms - (limit - index + 1) * step
                rows.append({
                    "open_time": open_time,
                    "close_time": open_time + step - 1,
                    "open": "100",
                    "high": "101",
                    "low": "99",
                    "close": "100.5",
                    "volume": "10",
                    "quote_volume": "1000",
                })
            klines[interval] = rows
        payload_symbols[symbol] = {
            "ticker": {
                "symbol": symbol,
                "lastPrice": "100.5",
                "bidPrice": "100.4",
                "askPrice": "100.6",
                "quoteVolume": "1000000",
                "priceChangePercent": "1.0",
                "_relay_event_time_ms": now_ms - stale_ticker_seconds * 1000,
                "_relay_transport": "WEBSOCKET",
            },
            "klines": klines,
        }
    return {
        "schema_version": 1,
        "source": "binance_spot_public_rest",
        "generated_at": "2026-10-11T00:00:00+00:00",
        "generated_at_ms": generated_ms,
        "symbol_count": len(payload_symbols),
        "symbols": payload_symbols,
        "bootstrap_only": True,
    }


def test_relay_bootstrap_seeds_candles_without_faking_live_health():
    feed = BinanceMarketStream(
        ["BTCUSDT"],
        intervals=("5m", "15m", "1h", "4h"),
        relay_url="wss://relay.example.test/stream",
        relay_token="r" * 64,
    )
    feed._consume_message(json.dumps({"type": "snapshot", "snapshot": _relay_snapshot(stale_ticker_seconds=120)}))

    assert len(feed.get_kline_history("BTCUSDT", "5m", 60)) == 60
    assert len(feed.get_kline_history("BTCUSDT", "15m", 150)) == 150
    assert ("BTCUSDT", "1h") in feed._runtime_kline_seeded
    assert ("BTCUSDT", "4h") in feed._runtime_kline_seeded
    assert feed._events_total == 0
    assert feed._last_event_at is None
    assert feed._fresh_ticker("BTCUSDT") is None
    health = feed.snapshot()
    assert health["event_stream_healthy"] is False
    assert health["kline_coverage_by_interval"] == {
        "5m": 0, "15m": 0, "1h": 0, "4h": 0
    }
    assert health["missing_kline_series"] == [
        "BTCUSDT:15m", "BTCUSDT:1h", "BTCUSDT:4h", "BTCUSDT:5m"
    ]

    # A real live event should change only its own series coverage.
    now_ms = int(time.time() * 1000)
    live_message = {
        "stream": "btcusdt@kline_5m",
        "data": {
            "e": "kline",
            "E": now_ms,
            "s": "BTCUSDT",
            "k": {
                "t": now_ms - 1_000,
                "T": now_ms + 299_000,
                "i": "5m",
                "o": "100",
                "h": "101",
                "l": "99",
                "c": "100.5",
                "v": "10",
                "q": "1000",
                "x": False,
            },
        },
    }
    feed._consume_message(json.dumps(live_message))
    health = feed.snapshot()
    assert health["kline_coverage_by_interval"]["5m"] == 1
    assert health["symbols_with_latest_kline"] == 1
    assert "BTCUSDT:5m" not in health["missing_kline_series"]


def test_relay_mode_never_falls_back_to_direct_binance_rest(monkeypatch):
    rest_calls = []
    fake_legacy = types.ModuleType("shadow_main_legacy")
    fake_legacy.fetch_24h_tickers = lambda requested=None: (
        rest_calls.append(("ticker", list(requested or []))) or {}
    )
    fake_legacy.fetch_klines = lambda symbol, interval, limit: (
        rest_calls.append(("kline", symbol, interval, limit)) or []
    )
    fake_legacy.fetch_strategy_data = lambda: None
    fake_legacy._BINANCE_MARKET_DATA_SYMBOL_SET = {"BTCUSDT"}
    fake_legacy._BYBIT_MARKET_DATA_SYMBOL_SET = set()
    fake_legacy._binance_ws_market_data_integration_installed = False
    previous = sys.modules.get("shadow_main_legacy")
    try:
        sys.modules["shadow_main_legacy"] = fake_legacy
        feed = BinanceMarketStream(
            ["BTCUSDT"],
            intervals=("5m", "15m", "1h", "4h"),
            relay_url="wss://relay.example.test/stream",
            relay_token="r" * 64,
        )
        feed._install_runtime_integration()
        feed._consume_relay_snapshot(_relay_snapshot())
        rows = fake_legacy.fetch_klines("BTCUSDT", "5m", 60)
        assert len(rows) == 60
        assert rest_calls == []

        # Show that a missing ticker stays missing even after live WS data was
        # previously observed; the external relay must not open a REST fallback.
        feed._connected = True
        feed._last_event_at = time.time()
        recent = dict(feed._latest_ticker["BTCUSDT"])
        recent["received_at"] = time.time()
        feed._latest_ticker["BTCUSDT"] = recent
        assert fake_legacy.fetch_24h_tickers(["BTCUSDT"])["BTCUSDT"]["market_data_source"] == "BINANCE"
        feed._fresh_ticker = lambda symbol: None
        assert fake_legacy.fetch_24h_tickers(["BTCUSDT"]) == {}
        assert rest_calls == []
    finally:
        if previous is None:
            sys.modules.pop("shadow_main_legacy", None)
        else:
            sys.modules["shadow_main_legacy"] = previous


def test_relay_mode_fails_closed_when_bootstrap_history_is_short():
    rest_calls = []
    fake_legacy = types.ModuleType("shadow_main_legacy")
    fake_legacy.fetch_24h_tickers = lambda requested=None: {}
    fake_legacy.fetch_klines = lambda symbol, interval, limit: (
        rest_calls.append((symbol, interval, limit)) or []
    )
    fake_legacy.fetch_strategy_data = lambda: None
    fake_legacy._BINANCE_MARKET_DATA_SYMBOL_SET = {"BTCUSDT"}
    fake_legacy._BYBIT_MARKET_DATA_SYMBOL_SET = set()
    fake_legacy._binance_ws_market_data_integration_installed = False
    previous = sys.modules.get("shadow_main_legacy")
    try:
        sys.modules["shadow_main_legacy"] = fake_legacy
        feed = BinanceMarketStream(
            ["BTCUSDT"],
            intervals=("5m", "15m", "1h", "4h"),
            relay_url="wss://relay.example.test/stream",
            relay_token="r" * 64,
        )
        feed._install_runtime_integration()
        short_snapshot = _relay_snapshot(rows_by_interval={"5m": 1, "15m": 1, "1h": 1, "4h": 1})
        feed._consume_relay_snapshot(short_snapshot)
        assert fake_legacy.fetch_klines("BTCUSDT", "5m", 60) == []
        assert rest_calls == []
    finally:
        if previous is None:
            sys.modules.pop("shadow_main_legacy", None)
        else:
            sys.modules["shadow_main_legacy"] = previous
