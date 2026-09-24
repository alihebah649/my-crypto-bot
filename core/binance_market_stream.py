"""Diagnostic-only Binance Spot WebSocket market feed.

This module observes the configured Spot universe without changing strategy,
risk, execution, persistence, or REST fallback behavior. It is the first stage
of the REST -> WebSocket migration: one combined WebSocket connection receives
ticker + kline updates so we can prove coverage/freshness before making the
stream authoritative.

Binance public market streams are used without API credentials.
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

import websockets


DEFAULT_BASE_URL = "wss://stream.binance.com:9443/stream"
DEFAULT_INTERVALS = ("5m", "15m", "1h", "4h")


@dataclass(frozen=True)
class StreamHealth:
    connected: bool
    stream_count: int
    last_event_age_seconds: float | None
    events_total: int
    kline_events: int
    ticker_events: int
    closed_kline_events: int
    reconnects: int
    parse_errors: int
    last_error: str | None


class BinanceMarketStream:
    """Single-connection shadow observer for Spot ticker + Kline streams."""

    def __init__(
        self,
        symbols: Iterable[str],
        *,
        intervals: Iterable[str] = DEFAULT_INTERVALS,
        base_url: str = DEFAULT_BASE_URL,
        reconnect_min_seconds: float = 2.0,
        reconnect_max_seconds: float = 60.0,
        stale_after_seconds: float = 30.0,
    ) -> None:
        self.symbols = tuple(dict.fromkeys(str(s).upper() for s in symbols if str(s).strip()))
        self.intervals = tuple(dict.fromkeys(str(i) for i in intervals))
        self.base_url = str(base_url).rstrip("/")
        self.reconnect_min_seconds = max(0.5, float(reconnect_min_seconds))
        self.reconnect_max_seconds = max(self.reconnect_min_seconds, float(reconnect_max_seconds))
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
        self._latest_ticker: dict[str, dict[str, Any]] = {}

    @property
    def stream_names(self) -> list[str]:
        result: list[str] = []
        for symbol in self.symbols:
            lower = symbol.lower()
            for interval in self.intervals:
                result.append(f"{lower}@kline_{interval}")
            result.append(f"{lower}@ticker")
        return result

    @property
    def stream_count(self) -> int:
        return len(self.stream_names)

    def build_url(self) -> str:
        streams = "/".join(self.stream_names)
        return f"{self.base_url}?streams={streams}"

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run_thread,
                daemon=True,
                name="binance-market-websocket-shadow",
            )
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run_thread(self) -> None:
        asyncio.run(self._run_loop())

    async def _run_loop(self) -> None:
        backoff = self.reconnect_min_seconds
        first_connect = True

        while not self._stop.is_set():
            try:
                async with websockets.connect(
                    self.build_url(),
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=5,
                    max_size=4 * 1024 * 1024,
                ) as websocket:
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
                with self._lock:
                    self._connected = False

    def _consume_message(self, message: str | bytes) -> None:
        try:
            raw = json.loads(message)
            payload = raw.get("data", raw) if isinstance(raw, Mapping) else raw
            if not isinstance(payload, Mapping):
                return

            event_type = str(payload.get("e") or "")
            now = time.time()
            with self._lock:
                self._events_total += 1
                self._last_event_at = now

            if event_type == "24hrTicker":
                self._consume_ticker(payload, now)
            elif event_type == "kline":
                self._consume_kline(payload, now)
        except Exception as exc:
            with self._lock:
                self._parse_errors += 1
                self._last_error = f"{type(exc).__name__}: {exc}"

    def _consume_ticker(self, payload: Mapping[str, Any], now: float) -> None:
        symbol = str(payload.get("s") or "").upper()
        if symbol not in self.symbols:
            return
        ticker = {
            "symbol": symbol,
            "lastPrice": _float(payload.get("c")),
            "bidPrice": _float(payload.get("b")),
            "askPrice": _float(payload.get("a")),
            "quoteVolume": _float(payload.get("q")),
            "priceChangePercent": _float(payload.get("P")),
            "event_time": payload.get("E"),
            "received_at": now,
        }
        with self._lock:
            self._ticker_events += 1
            self._latest_ticker[symbol] = ticker

    def _consume_kline(self, payload: Mapping[str, Any], now: float) -> None:
        symbol = str(payload.get("s") or "").upper()
        kline = payload.get("k")
        if symbol not in self.symbols or not isinstance(kline, Mapping):
            return
        interval = str(kline.get("i") or "")
        if interval not in self.intervals:
            return

        candle = {
            "open_time": _int(kline.get("t")),
            "close_time": _int(kline.get("T")),
            "open": _float(kline.get("o")),
            "high": _float(kline.get("h")),
            "low": _float(kline.get("l")),
            "close": _float(kline.get("c")),
            "volume": _float(kline.get("v")),
            "quote_volume": _float(kline.get("q")),
            "is_closed": bool(kline.get("x")),
            "event_time": payload.get("E"),
            "received_at": now,
        }
        with self._lock:
            self._kline_events += 1
            if candle["is_closed"]:
                self._closed_kline_events += 1
            self._latest_kline[(symbol, interval)] = candle

    def get_latest_kline(self, symbol: str, interval: str) -> dict[str, Any] | None:
        with self._lock:
            value = self._latest_kline.get((str(symbol).upper(), str(interval)))
            return dict(value) if isinstance(value, Mapping) else None

    def get_latest_ticker(self, symbol: str) -> dict[str, Any] | None:
        with self._lock:
            value = self._latest_ticker.get(str(symbol).upper())
            return dict(value) if isinstance(value, Mapping) else None

    def snapshot(self, *, now: float | None = None) -> dict[str, Any]:
        current = time.time() if now is None else float(now)
        with self._lock:
            last_age = (
                None
                if self._last_event_at is None
                else max(0.0, current - self._last_event_at)
            )
            latest_kline_count = len(self._latest_kline)
            latest_ticker_count = len(self._latest_ticker)
            return {
                "available": True,
                "mode": "SHADOW_ONLY",
                "connected": self._connected,
                "stream_count": self.stream_count,
                "symbol_count": len(self.symbols),
                "intervals": list(self.intervals),
                "symbols_with_latest_kline": latest_kline_count,
                "expected_kline_streams": len(self.symbols) * len(self.intervals),
                "tickers_with_latest": latest_ticker_count,
                "expected_tickers": len(self.symbols),
                "coverage_kline_percent": round(
                    latest_kline_count / float(max(1, len(self.symbols) * len(self.intervals))) * 100.0,
                    2,
                ),
                "coverage_ticker_percent": round(
                    latest_ticker_count / float(max(1, len(self.symbols))) * 100.0,
                    2,
                ),
                "last_event_age_seconds": None if last_age is None else round(last_age, 3),
                "event_stream_healthy": bool(
                    self._connected and last_age is not None and last_age <= self.stale_after_seconds
                ),
                "stale_after_seconds": self.stale_after_seconds,
                "events_total": self._events_total,
                "kline_events": self._kline_events,
                "ticker_events": self._ticker_events,
                "closed_kline_events": self._closed_kline_events,
                "reconnects": self._reconnects,
                "parse_errors": self._parse_errors,
                "last_error": self._last_error,
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


__all__ = ["BinanceMarketStream", "StreamHealth"]
