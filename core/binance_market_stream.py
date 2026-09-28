"""Binance Spot WebSocket market feed with Paper market-data integration.

The stream remains isolated from strategy/risk/execution decisions, but when the
Paper entrypoint is running it becomes the authoritative Binance ticker source
and overlays the latest closed 5m/15m candle onto the canonical kline path.
REST remains a cold-start/stale-data fallback only.
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
from typing import Any, Iterable, Mapping

import websockets

DEFAULT_BASE_URL = "wss://stream.binance.com:9443/stream"
DEFAULT_INTERVALS = ("5m", "15m", "1h", "4h")


class BinanceMarketStream:
    """Binance Spot ticker + kline stream used by the Paper market-data layer."""

    def __init__(self, symbols: Iterable[str], *, intervals: Iterable[str] = DEFAULT_INTERVALS, base_url: str = DEFAULT_BASE_URL, reconnect_min_seconds: float = 2.0, reconnect_max_seconds: float = 60.0, stale_after_seconds: float = 30.0) -> None:
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
        self._latest_closed_kline: dict[tuple[str, str], dict[str, Any]] = {}
        self._latest_ticker: dict[str, dict[str, Any]] = {}
        # Per-process Binance kline history. REST is used only to seed a
        # series when history is missing/insufficient; after that, closed and
        # live WebSocket candles keep the series current without repeated REST
        # refreshes.
        self._runtime_kline_history: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self._runtime_kline_seed_last_attempt: dict[tuple[str, str], float] = {}
        self._runtime_kline_rest_seed_count = 0
        self._runtime_kline_rest_retry_count = 0
        self._runtime_ticker_ws_hits = 0
        self._runtime_ticker_rest_fallbacks = 0
        self._runtime_kline_ws_overlays = 0
        self._runtime_integration_installed = False

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
        self._install_runtime_integration()
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._run_thread, daemon=True, name="binance-market-websocket-paper")
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
                async with websockets.connect(self.build_url(), ping_interval=20, ping_timeout=20, close_timeout=5, max_size=4 * 1024 * 1024) as websocket:
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
        ticker = {"symbol": symbol, "lastPrice": _float(payload.get("c")), "bidPrice": _float(payload.get("b")), "askPrice": _float(payload.get("a")), "quoteVolume": _float(payload.get("q")), "priceChangePercent": _float(payload.get("P")), "event_time": payload.get("E"), "received_at": now, "market_data_source": "BINANCE", "market_data_transport": "WEBSOCKET"}
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
        candle = {"open_time": _int(kline.get("t")), "close_time": _int(kline.get("T")), "open": _float(kline.get("o")), "high": _float(kline.get("h")), "low": _float(kline.get("l")), "close": _float(kline.get("c")), "volume": _float(kline.get("v")), "quote_volume": _float(kline.get("q")), "is_closed": bool(kline.get("x")), "event_time": payload.get("E"), "received_at": now, "market_data_source": "BINANCE", "market_data_transport": "WEBSOCKET"}
        with self._lock:
            self._kline_events += 1
            self._latest_kline[(symbol, interval)] = candle
            self._merge_runtime_kline_locked(symbol, interval, candle)
            if candle["is_closed"]:
                self._closed_kline_events += 1
                self._latest_closed_kline[(symbol, interval)] = candle

    def get_latest_kline(self, symbol: str, interval: str) -> dict[str, Any] | None:
        with self._lock:
            value = self._latest_kline.get((str(symbol).upper(), str(interval)))
            return dict(value) if isinstance(value, Mapping) else None

    def get_latest_closed_kline(self, symbol: str, interval: str) -> dict[str, Any] | None:
        with self._lock:
            value = self._latest_closed_kline.get((str(symbol).upper(), str(interval)))
            return dict(value) if isinstance(value, Mapping) else None

    def get_latest_ticker(self, symbol: str) -> dict[str, Any] | None:
        with self._lock:
            value = self._latest_ticker.get(str(symbol).upper())
            return dict(value) if isinstance(value, Mapping) else None

    def _fresh_ticker(self, symbol: str) -> dict[str, Any] | None:
        ticker = self.get_latest_ticker(symbol)
        if not ticker:
            return None
        received_at = _float(ticker.get("received_at"))
        if received_at <= 0 or time.time() - received_at > self.stale_after_seconds:
            return None
        return ticker

    def _merge_runtime_kline_locked(
        self,
        symbol: str,
        interval: str,
        candle: Mapping[str, Any],
    ) -> None:
        key = (str(symbol).upper(), str(interval))
        open_time = _int(candle.get("open_time"))
        if open_time <= 0:
            return
        history = self._runtime_kline_history.setdefault(key, [])
        replacement = dict(candle)
        for index, existing in enumerate(history):
            if _int(existing.get("open_time")) == open_time:
                history[index] = replacement
                break
        else:
            history.append(replacement)
        history.sort(key=lambda item: _int(item.get("open_time")))
        if len(history) > 500:
            del history[:-500]

    def _seed_runtime_kline_history(
        self,
        symbol: str,
        interval: str,
        candles: Iterable[Mapping[str, Any]],
    ) -> int:
        key = (str(symbol).upper(), str(interval))
        normalized: dict[int, dict[str, Any]] = {}
        for item in candles:
            if not isinstance(item, Mapping):
                continue
            open_time = _int(item.get("open_time"))
            if open_time <= 0:
                continue
            normalized[open_time] = dict(item)
        if not normalized:
            return 0
        with self._lock:
            existing = {
                _int(item.get("open_time")): dict(item)
                for item in self._runtime_kline_history.get(key, [])
                if _int(item.get("open_time")) > 0
            }
            existing.update(normalized)
            rows = [existing[key] for key in sorted(existing)]
            self._runtime_kline_history[key] = rows[-500:]
        return len(rows)

    def _runtime_kline_snapshot_rows(
        self,
        symbol: str,
        interval: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        key = (str(symbol).upper(), str(interval))
        with self._lock:
            rows = self._runtime_kline_history.get(key, [])
            if not rows:
                return []
            result = [dict(row) for row in rows]
        return result[-int(limit):] if limit and len(result) > int(limit) else result

    def _install_runtime_integration(self) -> None:
        """Install the smallest possible adapter into the existing Paper path."""
        if self._runtime_integration_installed:
            return
        try:
            import shadow_main_legacy as legacy
        except Exception:
            return
        if getattr(legacy, "_binance_ws_market_data_integration_installed", False):
            self._runtime_integration_installed = True
            return
        original_ticker_fetch = getattr(legacy, "fetch_24h_tickers", None)
        original_kline_fetch = getattr(legacy, "fetch_klines", None)
        if not callable(original_ticker_fetch) or not callable(original_kline_fetch):
            return
        binance_set = set(getattr(legacy, "_BINANCE_MARKET_DATA_SYMBOL_SET", ()))
        if not binance_set:
            split = len(self.symbols) // 2
            binance_set = set(self.symbols[:split])
        bybit_set = set(getattr(legacy, "_BYBIT_MARKET_DATA_SYMBOL_SET", ()))
        # shadow_main_base owns the venue split, but the legacy compatibility
        # module does not expose its Bybit symbol set. When that compatibility
        # attribute is absent, derive the complementary lane from the same
        # symbol universe used to derive the Binance lane above. This keeps
        # the WS adapter from silently dropping all Bybit tickers.
        if not bybit_set:
            bybit_set = set(self.symbols) - binance_set

        def fetch_tickers(symbols=None):
            requested = [str(s).upper() for s in (symbols if symbols is not None else self.symbols)]
            result: dict[str, dict] = {}
            ws_symbols = [s for s in requested if s in binance_set]
            fallback_symbols = []
            for symbol in ws_symbols:
                ticker = self._fresh_ticker(symbol)
                if ticker is None:
                    fallback_symbols.append(symbol)
                else:
                    result[symbol] = dict(ticker)
                    with self._lock:
                        self._runtime_ticker_ws_hits += 1
            if fallback_symbols:
                fallback = original_ticker_fetch(fallback_symbols)
                for symbol, ticker in fallback.items():
                    row = dict(ticker)
                    row.setdefault("market_data_source", "BINANCE")
                    row["market_data_transport"] = "REST_FALLBACK"
                    result[symbol] = row
                    with self._lock:
                        self._runtime_ticker_rest_fallbacks += 1
            bybit_symbols = [s for s in requested if s in bybit_set and s not in binance_set]
            if bybit_symbols:
                for symbol, ticker in original_ticker_fetch(bybit_symbols).items():
                    result[symbol] = dict(ticker)
            return {symbol: result[symbol] for symbol in requested if symbol in result}

        def fetch_klines(symbol: str, interval: str, limit: int):
            normalized_symbol = str(symbol).upper()
            normalized_interval = str(interval)
            if normalized_symbol not in binance_set or normalized_interval not in self.intervals:
                return original_kline_fetch(symbol, interval, limit)

            key = (normalized_symbol, normalized_interval)
            now = time.time()
            rows = self._runtime_kline_snapshot_rows(normalized_symbol, normalized_interval, limit)

            # REST is a cold-start seed, not a periodic refresh. Once the
            # series has enough history, WebSocket updates replace/append the
            # current candle and each newly closed candle in-place.
            if len(rows) < int(limit):
                with self._lock:
                    last_attempt = self._runtime_kline_seed_last_attempt.get(key, 0.0)
                    can_attempt = now - last_attempt >= 300.0
                    if can_attempt:
                        self._runtime_kline_seed_last_attempt[key] = now
                if can_attempt:
                    data = original_kline_fetch(symbol, interval, limit)
                    seeded_count = self._seed_runtime_kline_history(
                        normalized_symbol,
                        normalized_interval,
                        data or [],
                    )
                    with self._lock:
                        if seeded_count:
                            self._runtime_kline_rest_seed_count += 1
                        else:
                            self._runtime_kline_rest_retry_count += 1
                    rows = self._runtime_kline_snapshot_rows(
                        normalized_symbol,
                        normalized_interval,
                        limit,
                    )

            if not rows:
                return []

            with self._lock:
                self._runtime_kline_ws_overlays += 1
            return rows

        legacy.fetch_24h_tickers = fetch_tickers
        legacy.fetch_klines = fetch_klines

        # Critical binding: fetch_strategy_data is a function defined inside
        # shadow_main_legacy, so its global lookup table must explicitly point
        # at the WS-aware fetcher. Patching only the module attribute is not
        # sufficient when another wrapper has already captured the function.
        strategy_fetch = getattr(legacy, "fetch_strategy_data", None)
        strategy_globals = getattr(strategy_fetch, "__globals__", None)
        if isinstance(strategy_globals, dict):
            strategy_globals["fetch_24h_tickers"] = fetch_tickers
            strategy_globals["fetch_klines"] = fetch_klines

        legacy._binance_ws_market_data_integration_installed = True
        legacy.binance_market_stream = self
        self._runtime_integration_installed = True

    def snapshot(self, *, now: float | None = None) -> dict[str, Any]:
        current = time.time() if now is None else float(now)
        with self._lock:
            last_age = None if self._last_event_at is None else max(0.0, current - self._last_event_at)
            latest_kline_count = len(self._latest_kline)
            latest_ticker_count = len(self._latest_ticker)
            history_key_count = len(self._runtime_kline_history)
            history_rows = sum(len(rows) for rows in self._runtime_kline_history.values())
            return {"available": True, "mode": "PAPER_AUTHORITATIVE_BINANCE_WS", "connected": self._connected, "stream_count": self.stream_count, "symbol_count": len(self.symbols), "intervals": list(self.intervals), "symbols_with_latest_kline": latest_kline_count, "expected_kline_streams": len(self.symbols) * len(self.intervals), "tickers_with_latest": latest_ticker_count, "expected_tickers": len(self.symbols), "coverage_kline_percent": round(latest_kline_count / float(max(1, len(self.symbols) * len(self.intervals))) * 100.0, 2), "coverage_ticker_percent": round(latest_ticker_count / float(max(1, len(self.symbols))) * 100.0, 2), "last_event_age_seconds": None if last_age is None else round(last_age, 3), "event_stream_healthy": bool(self._connected and last_age is not None and last_age <= self.stale_after_seconds), "stale_after_seconds": self.stale_after_seconds, "events_total": self._events_total, "kline_events": self._kline_events, "ticker_events": self._ticker_events, "closed_kline_events": self._closed_kline_events, "reconnects": self._reconnects, "parse_errors": self._parse_errors, "last_error": self._last_error, "runtime_integration": {"installed": self._runtime_integration_installed, "ticker_ws_hits": self._runtime_ticker_ws_hits, "ticker_rest_fallbacks": self._runtime_ticker_rest_fallbacks, "kline_ws_overlays": self._runtime_kline_ws_overlays, "kline_rest_seeds": self._runtime_kline_rest_seed_count, "kline_rest_retries": self._runtime_kline_rest_retry_count, "kline_history_keys": history_key_count, "kline_history_rows": history_rows}}


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


__all__ = ["BinanceMarketStream"]
