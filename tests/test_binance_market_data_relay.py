from __future__ import annotations

import pytest

from tools.binance_market_data_relay import DEFAULT_LIMITS, RelayError, SYMBOLS, build_snapshot


def _raw_candle(open_time: int, close_time: int, close: str = "100.0") -> list:
    return [
        open_time, "99.0", "101.0", "98.0", close, "1000.0", close_time,
        "100000.0", 100, "500.0", "50000.0", "0",
    ]


def test_build_snapshot_covers_22_symbols_and_four_intervals() -> None:
    ticker_rows = [{"symbol": s, "lastPrice": "100.0"} for s in SYMBOLS]
    candles = {
        s: {
            tf: [_raw_candle(1_000 + i * 10, 1_005 + i * 10) for i in range(100)]
            for tf in ("5m", "15m", "1h", "4h")
        }
        for s in SYMBOLS
    }

    snapshot = build_snapshot(
        now_ms=2_000_000,
        ticker_rows=ticker_rows,
        candles=candles,
        limits={"5m": 100, "15m": 100, "1h": 100, "4h": 100},
    )

    assert snapshot["symbol_count"] == 22
    assert len(snapshot["symbols"]) == 22
    assert set(snapshot["symbols"]["BTCUSDT"]["klines"]) == {"5m", "15m", "1h", "4h"}
    assert len(snapshot["symbols"]["BTCUSDT"]["klines"]["5m"]) == 100



def test_default_snapshot_keeps_300_closed_5m_candles_when_rest_includes_open_bar() -> None:
    assert DEFAULT_LIMITS["5m"] == 301

    ticker_rows = [{"symbol": symbol, "lastPrice": "100.0"} for symbol in SYMBOLS]
    now_ms = 2_000_000_000
    candles = {}
    for symbol in SYMBOLS:
        candles[symbol] = {}
        for interval in ("5m", "15m", "1h", "4h"):
            rows = [
                _raw_candle(1_000_000_000 + index * 300_000, 1_000_000_299 + index * 300_000)
                for index in range(300 if interval == "5m" else 100)
            ]
            if interval == "5m":
                open_time = 1_090_000_000
                rows.append(_raw_candle(open_time, open_time + 299_999))
            candles[symbol][interval] = rows

    snapshot = build_snapshot(
        now_ms=now_ms,
        ticker_rows=ticker_rows,
        candles=candles,
    )

    for symbol in SYMBOLS:
        closed_5m = snapshot["symbols"][symbol]["klines"]["5m"]
        assert len(closed_5m) == 300
        assert all(int(row["close_time"]) < now_ms for row in closed_5m)
        assert closed_5m[-1]["open_time"] == 1_000_000_000 + 299 * 300_000

def test_build_snapshot_rejects_missing_ticker() -> None:
    ticker_rows = [{"symbol": s, "lastPrice": "100.0"} for s in SYMBOLS[:-1]]
    candles = {
        s: {
            tf: [_raw_candle(1_000 + i * 10, 1_005 + i * 10) for i in range(100)]
            for tf in ("5m", "15m", "1h", "4h")
        }
        for s in SYMBOLS
    }

    with pytest.raises(RelayError, match="Ticker coverage incomplete"):
        build_snapshot(
            now_ms=2_000_000,
            ticker_rows=ticker_rows,
            candles=candles,
            limits={"5m": 100, "15m": 100, "1h": 100, "4h": 100},
        )
