from __future__ import annotations

import threading
import time

from core.market_data_runtime_trace import install


class LegacyStub:
    def __init__(self):
        self._market_data_runtime_trace_installed = False
        self.kline_log = []
        self.logger = _LoggerStub()

        def fetch_klines(symbol, interval, limit):
            self.kline_log.append((symbol, interval, limit))
            return []

        def fetch_strategy_data():
            return {}, {}, {}

        def score_symbol(symbol, ticker, candles_15m, candles_5m):
            return {
                "symbol": symbol,
                "score": 72,
                "scalp_score": 72,
                "scalp_signal": "BUY",
            }

        self.fetch_klines = fetch_klines
        self.fetch_strategy_data = fetch_strategy_data
        self.score_symbol = score_symbol


class _LoggerStub:
    def info(self, *args, **kwargs):
        return None


def _candle(open_ms, close_ms):
    return {
        "open_time": open_ms,
        "close_time": close_ms,
        "open": 100.0,
        "high": 101.0,
        "low": 99.0,
        "close": 100.5,
        "volume": 10.0,
    }


def test_score_result_contains_exact_5m_decision_candle_freshness():
    now = time.time()
    candles = [
        _candle(int((now - 700) * 1000), int((now - 400) * 1000)),
        _candle(int((now - 399) * 1000), int((now - 80) * 1000)),
        _candle(int((now - 79) * 1000), int((now + 221) * 1000)),
    ]
    cache = {("BTCUSDT", "5m", 60): (now - 20.0, candles)}
    legacy = LegacyStub()

    install(
        legacy=legacy,
        kline_cache=cache,
        kline_cache_lock=threading.RLock(),
        kline_cache_ttl={"5m": 310.0},
    )

    result = legacy.score_symbol("BTCUSDT", {"lastPrice": 100.5}, candles, candles)
    audit = result["entry_freshness_5m"]

    assert audit["state"] == "FRESH"
    assert audit["decision_candle_close_time_ms"] == candles[-2]["close_time"]
    assert audit["latest_raw_candle_open"] is True
    assert audit["cache_expired"] is False
    assert result["scalp_signal"] == "BUY"


def test_score_result_marks_old_snapshot_stale_without_changing_signal():
    now = time.time()
    candles = [
        _candle(int((now - 1600) * 1000), int((now - 1300) * 1000)),
        _candle(int((now - 1299) * 1000), int((now - 999) * 1000)),
        _candle(int((now - 998) * 1000), int((now - 698) * 1000)),
    ]
    cache = {("ETHUSDT", "5m", 60): (now - 700.0, candles)}
    legacy = LegacyStub()

    install(
        legacy=legacy,
        kline_cache=cache,
        kline_cache_lock=threading.RLock(),
        kline_cache_ttl={"5m": 310.0},
    )

    result = legacy.score_symbol("ETHUSDT", {"lastPrice": 100.5}, candles, candles)
    audit = result["entry_freshness_5m"]

    assert audit["state"] == "STALE"
    assert audit["cache_expired"] is True
    assert audit["decision_candle_close_time_ms"] == candles[-2]["close_time"]
    assert result["scalp_signal"] == "BUY"
