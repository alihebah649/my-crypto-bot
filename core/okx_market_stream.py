"""OKX Spot public WebSocket market feed for an isolated Paper-only venue lab.

The stream subscribes only to public ticker and candle channels. It never logs
in, places orders, or shares candles with another venue.
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
from typing import Any, Iterable, Mapping

import websockets

DEFAULT_BASE_URL = "wss://ws.okx.com/ws/v5/public"
DEFAULT_BUSINESS_BASE_URL = "wss://ws.okx.com/ws/v5/business"
_INTERVAL_TO_CHANNEL = {
    "5m": "candle5m",
    "15m": "candle15m",
    "1h": "candle1H",
    "4h": "candle4H",
}
_INTERVAL_MS = {
    "5m": 300_000,
    "15m": 900_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
}
_HISTORY_LIMITS = {"5m": 60, "15m": 150, "1h": 60, "4h": 60}


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


def _symbol_from_inst_id(inst_id: str) -> str:
    return str(inst_id or "").replace("-", "").upper()


def _inst_id_from_symbol(symbol: str) -> str:
    normalized = str(symbol or "").upper()
    if normalized.endswith("USDT") and "-" not in normalized:
        return f"{normalized[:-4]}-USDT"
    return normalized


class OKXMarketStream:
    """Public OKX Spot ticker + kline stream used only by the Paper venue lab."""

    def __init__(
        self,
        symbols: Iterable[str],
        *,
        intervals: Iterable[str] = tuple(_INTERVAL_TO_CHANNEL),
        base_url: str = DEFAULT_BASE_URL,
        business_base_url: str = DEFAULT_BUSINESS_BASE_URL,
        reconnect_min_seconds: float = 2.0,
        reconnect_max_seconds: float = 60.0,
        stale_after_seconds: float = 30.0,
    ) -> None:
        self.symbols = tuple(dict.fromkeys(str(s).upper() for s in symbols if str(s).strip()))
        self.intervals = tuple(
            dict.fromkeys(str(i) for i in intervals if str(i) in _INTERVAL_TO_CHANNEL)
        )
        self.base_url = str(base_url).rstrip("/")
        self.business_base_url = str(business_base_url).rstrip("/")
        self.reconnect_min_seconds = max(0.5, float(reconnect_min_seconds))
        self.reconnect_max_seconds = max(self.reconnect_min_seconds, float(reconnect_max_seconds))
        self.stale_after_seconds = max(1.0, float(stale_after_seconds))
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._connected = False
        self._public_connected = False
        self._business_connected = False
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
        names = []
        for symbol in self.symbols:
            inst_id = _inst_id_from_symbol(symbol)
            names.append(f"tickers:{inst_id}")
            for interval in self.intervals:
                names.append(f"{_INTERVAL_TO_CHANNEL[interval]}:{inst_id}")
        return names

    @property
    def ticker_subscription_args(self) -> list[dict[str, str]]:
        return [
            {"channel": "tickers", "instId": _inst_id_from_symbol(symbol)}
            for symbol in self.symbols
        ]

    @property
    def candle_subscription_args(self) -> list[dict[str, str]]:
        return [
            {"channel": _INTERVAL_TO_CHANNEL[interval], "instId": _inst_id_from_symbol(symbol)}
            for symbol in self.symbols
            for interval in self.intervals
        ]

    @property
    def subscription_args(self) -> list[dict[str, str]]:
        """Combined subscription list for diagnostics and capacity tests."""
        return self.ticker_subscription_args + self.candle_subscription_args

    @staticmethod
    def _chunk_args(args: list[dict[str, str]], batch_size: int = 40) -> list[list[dict[str, str]]]:
        size = max(1, int(batch_size))
        return [args[i : i + size] for i in range(0, len(args), size)]

    @property
    def subscription_batches(self) -> list[list[dict[str, str]]]:
        return self._chunk_args(self.subscription_args, 40)

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
                name="okx-market-websocket-paper-lab",
            )
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run_thread(self) -> None:
        asyncio.run(self._run_loop())

    async def _heartbeat(self, websocket) -> None:
        # Each OKX connection is independent: ticker traffic on the public
        # socket must not suppress heartbeats on the quieter business candle
        # socket. A lightweight ping every 20 seconds keeps both paths alive.
        while not self._stop.is_set():
            await asyncio.sleep(20.0)
            if self._stop.is_set():
                return
            await websocket.send("ping")

    def _set_connection_state(self, connection: str, connected: bool, *, error: str | None = None) -> None:
        with self._lock:
            if connection == "public":
                self._public_connected = connected
            else:
                self._business_connected = connected
            self._connected = self._public_connected and self._business_connected
            if error is not None:
                self._last_error = error
            elif self._connected:
                self._last_error = None

    async def _run_connection(
        self,
        *,
        base_url: str,
        args: list[dict[str, str]],
        connection: str,
    ) -> None:
        if not args:
            self._set_connection_state(connection, False)
            return
        backoff = self.reconnect_min_seconds
        first_connect = True
        while not self._stop.is_set():
            heartbeat_task = None
            try:
                async with websockets.connect(
                    base_url,
                    ping_interval=None,
                    ping_timeout=None,
                    close_timeout=5,
                    max_size=4 * 1024 * 1024,
                ) as websocket:
                    for batch in self._chunk_args(args, 40):
                        await websocket.send(json.dumps({"op": "subscribe", "args": batch}))
                    heartbeat_task = asyncio.create_task(self._heartbeat(websocket))
                    with self._lock:
                        if not first_connect:
                            self._reconnects += 1
                    first_connect = False
                    backoff = self.reconnect_min_seconds
                    self._set_connection_state(connection, True)

                    async for message in websocket:
                        if self._stop.is_set():
                            break
                        if message == "ping":
                            await websocket.send("pong")
                            with self._lock:
                                self._last_event_at = time.time()
                            continue
                        if message == "pong":
                            with self._lock:
                                self._last_event_at = time.time()
                            continue
                        self._consume_message(message)
            except Exception as exc:
                self._set_connection_state(
                    connection,
                    False,
                    error=f"{connection.upper()}_WS {type(exc).__name__}: {exc}",
                )
                if self._stop.is_set():
                    break
                await asyncio.sleep(backoff)
                backoff = min(self.reconnect_max_seconds, backoff * 2.0)
            finally:
                if heartbeat_task is not None:
                    heartbeat_task.cancel()
                self._set_connection_state(connection, False)

    async def _run_loop(self) -> None:
        # OKX does not serve candlestick subscriptions from the ticker-only
        # public endpoint; both connections are read-only and independently
        # reconnect, while the combined health is healthy only when both are up.
        await asyncio.gather(
            self._run_connection(
                base_url=self.base_url,
                args=self.ticker_subscription_args,
                connection="public",
            ),
            self._run_connection(
                base_url=self.business_base_url,
                args=self.candle_subscription_args,
                connection="business",
            ),
        )

    def _consume_message(self, message: str | bytes) -> None:
        if message == "pong":
            with self._lock:
                self._last_event_at = time.time()
            return
        try:
            raw = json.loads(message)
            if not isinstance(raw, Mapping):
                return
            now = time.time()
            if str(raw.get("event") or "").lower() == "error":
                with self._lock:
                    self._events_total += 1
                    self._last_event_at = now
                    self._last_error = f"OKX WS error code={raw.get('code')} msg={raw.get('msg')}"
                return
            arg = raw.get("arg")
            data = raw.get("data")
            if not isinstance(arg, Mapping) or not isinstance(data, list):
                # Subscribe acknowledgements carry no market data.
                return
            channel = str(arg.get("channel") or "")
            inst_id = str(arg.get("instId") or "")
            symbol = _symbol_from_inst_id(inst_id)
            if symbol not in self.symbols:
                return
            with self._lock:
                self._events_total += 1
                self._last_event_at = now
            if channel == "tickers":
                self._consume_ticker(data, symbol, now, raw.get("ts"))
            else:
                self._consume_kline(data, symbol, channel, now, raw.get("ts"))
        except Exception as exc:
            with self._lock:
                self._parse_errors += 1
                self._last_error = f"{type(exc).__name__}: {exc}"

    def _consume_ticker(self, data: list[Any], symbol: str, now: float, event_time: Any) -> None:
        for item in data:
            if not isinstance(item, Mapping):
                continue
            last = _float(item.get("last"))
            row = {
                "symbol": symbol,
                "lastPrice": last,
                "bidPrice": _float(item.get("bidPx"), last) or last,
                "askPrice": _float(item.get("askPx"), last) or last,
                "volume": _float(item.get("vol24h")),
                "quoteVolume": _float(item.get("volCcy24h")),
                "priceChangePercent": (
                    (last - _float(item.get("open24h"))) / _float(item.get("open24h")) * 100.0
                    if _float(item.get("open24h")) > 0 else 0.0
                ),
                "highPrice": _float(item.get("high24h")),
                "lowPrice": _float(item.get("low24h")),
                "event_time": event_time,
                "received_at": now,
                "market_data_source": "OKX",
                "market_data_transport": "WEBSOCKET",
            }
            with self._lock:
                self._ticker_events += 1
                self._latest_ticker[symbol] = row

    def _consume_kline(
        self,
        data: list[Any],
        symbol: str,
        channel: str,
        now: float,
        event_time: Any,
    ) -> None:
        interval = next(
            (name for name, expected_channel in _INTERVAL_TO_CHANNEL.items() if expected_channel == channel),
            None,
        )
        if interval is None:
            return
        interval_ms = _INTERVAL_MS[interval]
        for item in data:
            if not isinstance(item, (list, tuple)) or len(item) < 6:
                continue
            try:
                open_time = int(item[0])
                open_price, high_price, low_price, close_price = (
                    float(item[1]), float(item[2]), float(item[3]), float(item[4])
                )
                volume = float(item[5])
            except (TypeError, ValueError):
                continue
            closed = str(item[8]) == "1" if len(item) > 8 else False
            candle = {
                "open_time": open_time,
                "close_time": open_time + interval_ms - 1,
                "open": open_price,
                "high": high_price,
                "low": low_price,
                "close": close_price,
                "volume": volume,
                "quote_volume": _float(item[7] if len(item) > 7 else 0.0),
                "is_closed": closed,
                "event_time": event_time,
                "received_at": now,
                "market_data_source": "OKX",
                "market_data_transport": "WEBSOCKET",
            }
            with self._lock:
                self._kline_events += 1
                self._latest_kline[(symbol, interval)] = candle
                self._merge_history_locked(symbol, interval, candle)
                if closed:
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
                row.setdefault("market_data_source", "OKX")
                row.setdefault("market_data_transport", "REST_COLD_START")
                self._merge_history_locked(key[0], key[1], row)
                count += 1
        return count

    def get_kline_history(self, symbol: str, interval: str, limit: int) -> list[dict[str, Any]]:
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
            expected = max(1, len(self.symbols) * len(self.intervals))
            return {
                "available": True,
                "mode": "PAPER_VENUE_LAB_OKX_WS",
                "connected": self._connected,
                "public_connected": self._public_connected,
                "business_connected": self._business_connected,
                "public_url": self.base_url,
                "business_url": self.business_base_url,
                "stream_count": self.stream_count,
                "symbol_count": len(self.symbols),
                "intervals": list(self.intervals),
                "expected_kline_streams": len(self.symbols) * len(self.intervals),
                "expected_tickers": len(self.symbols),
                "symbols_with_latest_kline": latest_klines,
                "tickers_with_latest": latest_tickers,
                "coverage_kline_percent": round(latest_klines / expected * 100.0, 2),
                "coverage_ticker_percent": round(latest_tickers / float(max(1, len(self.symbols))) * 100.0, 2),
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


__all__ = ["OKXMarketStream"]
