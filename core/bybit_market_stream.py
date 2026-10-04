"""Bybit Spot public WebSocket market stream for Paper-only venue lab runs.

This module has no account, order, or execution responsibilities. It keeps a
small in-process ticker/candle history so the venue lab can run 22/22 symbols
from Bybit without periodic REST polling. REST is reserved for cold-start
history seeding by the surrounding market-data guard.
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
from typing import Any, Iterable, Mapping

import websockets

DEFAULT_BASE_URL = "wss://stream.bybit.com/v5/public/spot"
_INTERVAL_TO_BYBIT = {
    "5m": "5",
    "15m": "15",
    "1h": "60",
    "4h": "240",
}
_HISTORY_LIMITS = {"5m": 60, "15m": 150, "1h": 60, "4h": 60}


class BybitMarketStream:
    """Bybit Spot ticker + kline stream used only by the venue comparison lab."""

    def __init__(
        self,
        symbols: Iterable[str],
        *,
        intervals: Iterable[str] = tuple(_INTERVAL_TO_BYBIT),
        base_url: str = DEFAULT_BASE_URL,
        reconnect_min_seconds: float = 2.0,
        reconnect_max_seconds: float = 60.0,
        stale_after_seconds: float = 30.0,
    ) -> None:
        self.symbols = tuple(dict.fromkeys(str(s).upper() for s in symbols if str(s).strip()))
        self.intervals = tuple(
            dict.fromkeys(str(i) for i in intervals if str(i) in _INTERVAL_TO_BYBIT)
        )
        self.base_url = str(base_url).rstrip("/")
        self.reconnect_min_seconds = max(0.5, float(reconnect_min_seconds))
        self.reconnect_max_seconds = max(
            self.reconnect_min_seconds, float(reconnect_max_seconds)
        )
        self.stale_after_seconds = max(1.0, float(stale_after_seconds))
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._connected = False
        self._last_event_at: float | None = None
        self._events_total = 0
        self._kline_events = 0
        self._ticker_events = 0
        self._closed_kline_events = 0
        self._reconnects = 0
        self._parse_errors = 0
        self._last_error: str | None = None
        self._latest_kline: dict[tuple[str, str], dict[str, Any]] = {}
        self._latest_closed_kline: dict[tuple[str, str], dict[str, Any]] = {}
        self._latest_ticker: dict[str, dict[str, Any]] = {}
        self._runtime_kline_history: dict[tuple[str, str], list[dict[str, Any]]] = {}

    @property
    def topic_names(self) -> list[str]:
        topics: list[str] = []
        for symbol in self.symbols:
            topics.append(f"tickers.{symbol}")
            for interval in self.intervals:
                topics.append(f"kline.{_INTERVAL_TO_BYBIT[interval]}.{symbol}")
        return topics

    @property
    def stream_count(self) -> int:
        return len(self.topic_names)

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run_thread,
                daemon=True,
                name="bybit-market-websocket-paper-lab",
            )
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run_thread(self) -> None:
        asyncio.run(self._run_loop())

    async def _heartbeat(self, websocket) -> None:
        while not self._stop.is_set():
            await asyncio.sleep(20.0)
            if self._stop.is_set():
                return
            await websocket.send(json.dumps({"op": "ping"}))

    async def _run_loop(self) -> None:
        backoff = self.reconnect_min_seconds
        first_connect = True
        while not self._stop.is_set():
            heartbeat_task = None
            try:
                async with websockets.connect(
                    self.base_url,
                    ping_interval=None,
                    ping_timeout=None,
                    close_timeout=5,
                    max_size=4 * 1024 * 1024,
                ) as websocket:
                    await websocket.send(
                        json.dumps(
                            {
                                "op": "subscribe",
                                "args": self.topic_names,
                            }
                        )
                    )
                    heartbeat_task = asyncio.create_task(self._heartbeat(websocket))
                    with self._lock:
                        self._connected = True
                        self._last_error = None
                        if not first_connect:
                            self._reconnects += 1
                    first_connect = False
                    backoff = self.reconnect_min_seconds

                    async for message in websocket:
                        if self._stop.is_set():
                            break
                        self._consume_message(message)
            except Exception as exc:
                with self._lock:
                    self._connected = False
                    self._last_error = f"{type(exc).__name__}: {exc}"
                if self._stop.is_set():
                    break
                await asyncio.sleep(backoff)
                backoff = min(self.reconnect_max_seconds, backoff * 2.0)
            finally:
                if heartbeat_task is not None:
                    heartbeat_task.cancel()
                with self._lock:
                    self._connected = False

    def _consume_message(self, message: str | bytes) -> None:
        try:
            raw = json.loads(message)
            if not isinstance(raw, Mapping):
                return
            topic = str(raw.get("topic") or "")
            now = time.time()
            with self._lock:
                self._events_total += 1
                self._last_event_at = now
            if topic.startswith("tickers."):
                self._consume_ticker(raw, now)
            elif topic.startswith("kline."):
                self._consume_kline(raw, now)
        except Exception as exc:
            with self._lock:
                self._parse_errors += 1
                self._last_error = f"{type(exc).__name__}: {exc}"

    def _consume_ticker(self, payload: Mapping[str, Any], now: float) -> None:
        data = payload.get("data")
        items = data if isinstance(data, list) else [data]
        for item in items:
            if not isinstance(item, Mapping):
                continue
            symbol = str(item.get("symbol") or "").upper()
            if symbol not in self.symbols:
                continue
            row = {
                "symbol": symbol,
                "lastPrice": _float(item.get("lastPrice")),
                "bidPrice": _float(item.get("bid1Price")),
                "askPrice": _float(item.get("ask1Price")),
                "quoteVolume": _float(item.get("turnover24h")),
                "volume": _float(item.get("volume24h")),
                "priceChangePercent": _float(item.get("price24hPcnt")) * 100.0,
                "highPrice": _float(item.get("highPrice24h")),
                "lowPrice": _float(item.get("lowPrice24h")),
                "event_time": payload.get("ts"),
                "received_at": now,
                "market_data_source": "BYBIT",
                "market_data_transport": "WEBSOCKET",
            }
            with self._lock:
                self._ticker_events += 1
                self._latest_ticker[symbol] = row

    def _consume_kline(self, payload: Mapping[str, Any], now: float) -> None:
        topic = str(payload.get("topic") or "")
        parts = topic.split(".")
        if len(parts) != 3:
            return
        interval_raw = parts[1]
        symbol = parts[2].upper()
        interval = next(
            (name for name, raw in _INTERVAL_TO_BYBIT.items() if raw == interval_raw),
            None,
        )
        if interval is None or symbol not in self.symbols:
            return
        data = payload.get("data")
        items = data if isinstance(data, list) else [data]
        for item in items:
            if not isinstance(item, Mapping):
                continue
            candle = {
                "open_time": _int(item.get("start")),
                "close_time": _int(item.get("end")),
                "open": _float(item.get("open")),
                "high": _float(item.get("high")),
                "low": _float(item.get("low")),
                "close": _float(item.get("close")),
                "volume": _float(item.get("volume")),
                "quote_volume": _float(item.get("turnover")),
                "is_closed": bool(item.get("confirm")),
                "event_time": payload.get("ts"),
                "received_at": now,
                "market_data_source": "BYBIT",
                "market_data_transport": "WEBSOCKET",
            }
            with self._lock:
                self._kline_events += 1
                self._latest_kline[(symbol, interval)] = candle
                self._merge_history_locked(symbol, interval, candle)
                if candle["is_closed"]:
                    self._closed_kline_events += 1
                    self._latest_closed_kline[(symbol, interval)] = dict(candle)

    def _merge_history_locked(
        self,
        symbol: str,
        interval: str,
        candle: Mapping[str, Any],
    ) -> None:
        key = (symbol, interval)
        open_time = _int(candle.get("open_time"))
        if open_time <= 0:
            return
        history = self._runtime_kline_history.setdefault(key, [])
        replacement = dict(candle)
        for idx, existing in enumerate(history):
            if _int(existing.get("open_time")) == open_time:
                history[idx] = replacement
                break
        else:
            history.append(replacement)
        history.sort(key=lambda item: _int(item.get("open_time")))
        max_rows = int(_HISTORY_LIMITS.get(interval, 60))
        if len(history) > max_rows:
            del history[:-max_rows]

    def seed_kline_history(
        self,
        symbol: str,
        interval: str,
        candles: Iterable[Mapping[str, Any]],
    ) -> int:
        key = (str(symbol).upper(), str(interval))
        count = 0
        with self._lock:
            for item in candles:
                if not isinstance(item, Mapping):
                    continue
                open_time = _int(item.get("open_time"))
                if open_time <= 0:
                    continue
                row = dict(item)
                row.setdefault("market_data_source", "BYBIT")
                row.setdefault("market_data_transport", "REST_COLD_START")
                self._merge_history_locked(key[0], key[1], row)
                count += 1
        return count

    def get_kline_history(
        self,
        symbol: str,
        interval: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        key = (str(symbol).upper(), str(interval))
        with self._lock:
            rows = [dict(row) for row in self._runtime_kline_history.get(key, [])]
        return rows[-int(limit):] if limit and len(rows) > int(limit) else rows

    def get_latest_ticker(self, symbol: str) -> dict[str, Any] | None:
        with self._lock:
            value = self._latest_ticker.get(str(symbol).upper())
            return dict(value) if isinstance(value, Mapping) else None

    def get_latest_closed_kline(self, symbol: str, interval: str) -> dict[str, Any] | None:
        with self._lock:
            value = self._latest_closed_kline.get((str(symbol).upper(), str(interval)))
            return dict(value) if isinstance(value, Mapping) else None

    def snapshot(self, *, now: float | None = None) -> dict[str, Any]:
        current = time.time() if now is None else float(now)
        with self._lock:
            age = None if self._last_event_at is None else max(0.0, current - self._last_event_at)
            key_count = len(self._runtime_kline_history)
            row_count = sum(len(rows) for rows in self._runtime_kline_history.values())
            latest_tickers = len(self._latest_ticker)
            latest_klines = len(self._latest_kline)
            return {
                "available": True,
                "mode": "PAPER_VENUE_LAB_BYBIT_WS",
                "connected": self._connected,
                "stream_count": self.stream_count,
                "symbol_count": len(self.symbols),
                "intervals": list(self.intervals),
                "expected_kline_streams": len(self.symbols) * len(self.intervals),
                "expected_tickers": len(self.symbols),
                "symbols_with_latest_kline": latest_klines,
                "tickers_with_latest": latest_tickers,
                "coverage_kline_percent": round(
                    latest_klines / float(max(1, len(self.symbols) * len(self.intervals))) * 100.0,
                    2,
                ),
                "coverage_ticker_percent": round(
                    latest_tickers / float(max(1, len(self.symbols))) * 100.0,
                    2,
                ),
                "last_event_age_seconds": None if age is None else round(age, 3),
                "event_stream_healthy": bool(
                    self._connected and age is not None and age <= self.stale_after_seconds
                ),
                "stale_after_seconds": self.stale_after_seconds,
                "events_total": self._events_total,
                "kline_events": self._kline_events,
                "ticker_events": self._ticker_events,
                "closed_kline_events": self._closed_kline_events,
                "reconnects": self._reconnects,
                "parse_errors": self._parse_errors,
                "last_error": self._last_error,
                "kline_history_keys": key_count,
                "kline_history_rows": row_count,
            }


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


__all__ = ["BybitMarketStream"]
