from __future__ import annotations

import json
import time

from market_data_relay.app import (
    CLIENT_HISTORY_LIMITS,
    RelayState,
    authorized,
    compact_snapshot,
)
from tools.binance_market_data_relay import INTERVALS, SYMBOLS


def _snapshot(rows_per_interval: int = 165) -> dict:
    symbols = {}
    generated_ms = int(time.time() * 1000)
    for symbol in SYMBOLS:
        ticker = {
            "symbol": symbol,
            "lastPrice": "100.0",
            "bidPrice": "99.9",
            "askPrice": "100.1",
            "quoteVolume": "1000000",
            "priceChangePercent": "1.0",
        }
        klines = {}
        for interval in INTERVALS:
            rows = []
            for index in range(rows_per_interval):
                open_time = (index + 1) * 60_000
                rows.append({
                    "open_time": open_time,
                    "open": "100",
                    "high": "101",
                    "low": "99",
                    "close": "100.5",
                    "volume": "10",
                    "close_time": open_time + 59_999,
                    "quote_volume": "1000",
                    "trade_count": 10,
                    "taker_buy_base_volume": "5",
                    "taker_buy_quote_volume": "500",
                })
            klines[interval] = rows
        symbols[symbol] = {"ticker": ticker, "klines": klines}
    return {
        "schema_version": 1,
        "source": "binance_spot_public_rest",
        "generated_at": "2026-10-11T00:00:00+00:00",
        "generated_at_ms": generated_ms,
        "symbol_count": len(SYMBOLS),
        "symbols": symbols,
    }


def test_bearer_auth_rejects_missing_wrong_and_short_tokens():
    secret = "a" * 64
    assert authorized(f"Bearer {secret}", secret)
    assert not authorized(None, secret)
    assert not authorized("Basic abc", secret)
    assert not authorized(f"Bearer {'b' * 64}", secret)
    assert not authorized(f"Bearer {'a' * 64}", "short")


def test_compact_snapshot_limits_depth_and_preserves_full_universe():
    payload = compact_snapshot(_snapshot(rows_per_interval=170))
    assert payload["symbol_count"] == 22
    assert set(payload["symbols"]) == set(SYMBOLS)
    for symbol in SYMBOLS:
        for interval, limit in CLIENT_HISTORY_LIMITS.items():
            assert len(payload["symbols"][symbol]["klines"][interval]) == limit


def test_closed_kline_event_updates_history_but_open_kline_does_not():
    state = RelayState(token="s" * 64, snapshot_path="/tmp/nonexistent-relay-cache.json")
    state.snapshot = _snapshot(rows_per_interval=5)
    symbol = SYMBOLS[0]
    baseline = len(state.snapshot["symbols"][symbol]["klines"]["5m"])
    event = {
        "stream": f"{symbol.lower()}@kline_5m",
        "data": {
            "e": "kline",
            "E": 1_700_001_000_500,
            "s": symbol,
            "k": {
                "t": 1_700_001_000_000,
                "T": 1_700_001_299_999,
                "i": "5m",
                "o": "100",
                "h": "102",
                "l": "99",
                "c": "101",
                "v": "25",
                "q": "2525",
                "n": 12,
                "V": "12",
                "Q": "1212",
                "x": False,
            },
        },
    }
    state._apply_market_event(json.dumps(event))
    assert len(state.snapshot["symbols"][symbol]["klines"]["5m"]) == baseline

    event["data"]["k"]["x"] = True
    state._apply_market_event(json.dumps(event))
    rows = state.snapshot["symbols"][symbol]["klines"]["5m"]
    assert len(rows) == baseline + 1
    assert rows[-1]["_relay_transport"] == "WEBSOCKET"
    assert rows[-1]["close"] == "101"
    assert state._closed_candle_count == 1


def test_rest_refresh_merge_does_not_overwrite_newer_live_candle():
    state = RelayState(token="s" * 64, snapshot_path="/tmp/nonexistent-relay-cache.json")
    old = _snapshot(rows_per_interval=5)
    symbol = SYMBOLS[0]
    old_row = dict(old["symbols"][symbol]["klines"]["5m"][-1])
    old_row.update({"close": "999", "_relay_transport": "WEBSOCKET"})
    old["symbols"][symbol]["klines"]["5m"][-1] = old_row
    state.snapshot = old

    fresh = _snapshot(rows_per_interval=5)
    fresh["symbols"][symbol]["klines"]["5m"][-1]["close"] = "111"
    state._merge_rest_snapshot(fresh)
    rows = state.snapshot["symbols"][symbol]["klines"]["5m"]
    assert rows[-1]["close"] == "999"
    assert rows[-1]["_relay_transport"] == "WEBSOCKET"



def test_live_candle_update_does_not_reset_rest_refresh_clock():
    state = RelayState(token="r" * 64, snapshot_path="/tmp/nonexistent-relay-cache.json")
    state._merge_rest_snapshot(_snapshot(rows_per_interval=165))
    rest_refresh_time = state.last_rest_refresh_at
    rest_refresh_ms = int(rest_refresh_time * 1000)

    now_ms = int(time.time() * 1000)
    symbol = SYMBOLS[0]
    event = {
        "stream": f"{symbol.lower()}@kline_5m",
        "data": {
            "e": "kline",
            "E": now_ms,
            "s": symbol,
            "k": {
                "t": now_ms - 300_000,
                "T": now_ms - 1,
                "i": "5m",
                "o": "100",
                "h": "102",
                "l": "99",
                "c": "101",
                "v": "25",
                "q": "2525",
                "n": 12,
                "V": "12",
                "Q": "1212",
                "x": True,
            },
        },
    }
    state._apply_market_event(json.dumps(event))

    assert state.last_rest_refresh_at == rest_refresh_time
    assert state.snapshot["_relay_meta"]["last_rest_refresh_at_ms"] == rest_refresh_ms



def test_persisted_rest_refresh_clock_is_not_advanced_by_live_candles(tmp_path):
    source = RelayState(token="p" * 64, snapshot_path=tmp_path / "source.json")
    source._merge_rest_snapshot(_snapshot(rows_per_interval=165))
    rest_refresh_ms = source.snapshot["_relay_meta"]["last_rest_refresh_at_ms"]

    # The market timestamp may be newer than the last successful REST repair.
    persisted_rest_refresh_ms = rest_refresh_ms - 600_000
    source.snapshot["_relay_meta"]["last_rest_refresh_at_ms"] = persisted_rest_refresh_ms
    source._write_snapshot_atomic(source.snapshot)

    restored = RelayState(token="p" * 64, snapshot_path=tmp_path / "source.json")
    assert restored.load_persisted_snapshot()
    assert int(restored.last_rest_refresh_at * 1000) == persisted_rest_refresh_ms
