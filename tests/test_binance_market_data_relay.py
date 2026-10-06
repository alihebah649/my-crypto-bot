from __future__ import annotations

import pytest

from tools.binance_market_data_relay import RelayError, SYMBOLS, build_snapshot


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
