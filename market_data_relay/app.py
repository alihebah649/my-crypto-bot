"""Authenticated, continuously streaming Binance Spot market-data relay.

This process runs outside Render. It owns the single upstream Binance market
WebSocket and fans out messages to authenticated consumers. A validated REST
snapshot seeds closed candle history; consumers must still observe fresh live
events before treating data as current.
"""
from __future__ import annotations

import asyncio
import copy
import hmac
import json
import logging
import os
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from aiohttp import WSMsgType, web
import websockets

from tools.binance_market_data_relay import (
    DEFAULT_LIMITS as RELAY_HISTORY_LIMITS,
    INTERVALS,
    SYMBOLS,
    RelayError,
    fetch_snapshot,
)

LOG = logging.getLogger("binance-market-data-relay")
LIVE_WS_BASE = os.getenv("BINANCE_WS_BASE", "wss://stream.binance.com:9443/stream").rstrip("/")
REST_REFRESH_AFTER_SECONDS = max(60.0, float(os.getenv("RELAY_REST_REFRESH_AFTER_SECONDS", "900")))
EVENT_STALE_AFTER_SECONDS = max(10.0, float(os.getenv("RELAY_EVENT_STALE_AFTER_SECONDS", "45")))
PERSIST_INTERVAL_SECONDS = max(1.0, float(os.getenv("RELAY_PERSIST_INTERVAL_SECONDS", "3")))
CLIENT_HISTORY_LIMITS = {"5m": 60, "15m": 150, "1h": 60, "4h": 60}
BOOTSTRAP_MAX_AGE_SECONDS = 10 * 365 * 24 * 60 * 60


def _utc_iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).isoformat()


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def authorized(authorization_header: str | None, expected_token: str) -> bool:
    """Check a bearer token without exposing either value in logs."""
    if not expected_token or len(expected_token) < 32:
        return False
    prefix = "Bearer "
    if not isinstance(authorization_header, str) or not authorization_header.startswith(prefix):
        return False
    supplied = authorization_header[len(prefix):].strip()
    return bool(supplied) and hmac.compare_digest(supplied, expected_token)


def _snapshot_is_valid(snapshot: Any) -> bool:
    """Validate the complete relay snapshot without depending on bot internals."""
    if not isinstance(snapshot, dict):
        return False
    if _int(snapshot.get("schema_version")) != 1:
        return False
    if str(snapshot.get("source", "")) != "binance_spot_public_rest":
        return False
    generated_ms = _int(snapshot.get("generated_at_ms"))
    if generated_ms <= 0:
        return False
    now = time.time()
    age = now - generated_ms / 1000.0
    if age < -30.0 or age > BOOTSTRAP_MAX_AGE_SECONDS:
        return False
    symbols = snapshot.get("symbols")
    if not isinstance(symbols, Mapping) or set(symbols) != set(SYMBOLS):
        return False
    if _int(snapshot.get("symbol_count"), -1) != len(SYMBOLS):
        return False
    now_ms = int(now * 1000)
    required = {"open_time", "close_time", "open", "high", "low", "close", "volume"}
    for symbol in SYMBOLS:
        item = symbols.get(symbol)
        if not isinstance(item, Mapping):
            return False
        if not isinstance(item.get("ticker"), Mapping):
            return False
        klines = item.get("klines")
        if not isinstance(klines, Mapping):
            return False
        for interval, limit in CLIENT_HISTORY_LIMITS.items():
            rows = klines.get(interval)
            if not isinstance(rows, list) or len(rows) < limit:
                return False
            previous_open = -1
            for row in rows:
                if not isinstance(row, Mapping) or not required.issubset(row):
                    return False
                open_time = _int(row.get("open_time"))
                close_time = _int(row.get("close_time"))
                if open_time <= previous_open or close_time <= open_time or close_time >= now_ms:
                    return False
                previous_open = open_time
    return True


def compact_snapshot(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Trim the REST snapshot to the strategy history depth before streaming."""
    symbols_in = snapshot.get("symbols")
    if not isinstance(symbols_in, Mapping) or set(symbols_in) != set(SYMBOLS):
        raise ValueError("snapshot symbol coverage mismatch")
    symbols_out: dict[str, Any] = {}
    for symbol in SYMBOLS:
        item = symbols_in.get(symbol)
        if not isinstance(item, Mapping):
            raise ValueError(f"invalid snapshot symbol: {symbol}")
        ticker = item.get("ticker")
        klines = item.get("klines")
        if not isinstance(ticker, Mapping) or not isinstance(klines, Mapping):
            raise ValueError(f"invalid snapshot payload: {symbol}")
        compact_klines: dict[str, list[dict[str, Any]]] = {}
        for interval, limit in CLIENT_HISTORY_LIMITS.items():
            rows = klines.get(interval)
            if not isinstance(rows, list):
                raise ValueError(f"missing {symbol} {interval} history")
            compact_klines[interval] = [dict(row) for row in rows[-limit:]]
        symbols_out[symbol] = {"ticker": dict(ticker), "klines": compact_klines}
    generated_ms = _int(snapshot.get("generated_at_ms"))
    return {
        "schema_version": 1,
        "source": "binance_spot_public_rest",
        "generated_at": snapshot.get("generated_at") or _utc_iso(generated_ms),
        "generated_at_ms": generated_ms,
        "symbol_count": len(SYMBOLS),
        "symbols": symbols_out,
        "bootstrap_only": True,
    }


class RelayState:
    """Current market snapshot, upstream socket, and downstream fan-out queues."""

    def __init__(
        self,
        *,
        token: str,
        snapshot_path: str | Path = "/data/latest-market-data.json",
        ws_base: str = LIVE_WS_BASE,
    ) -> None:
        if len(str(token or "")) < 32:
            raise ValueError("RELAY_SHARED_TOKEN must contain at least 32 characters")
        self.token = str(token)
        self.snapshot_path = Path(snapshot_path)
        self.ws_base = str(ws_base).rstrip("/")
        self.snapshot: dict[str, Any] | None = None
        self.upstream_connected = False
        self.last_event_at: float | None = None
        self.last_error: str | None = None
        self.last_refresh_error: str | None = None
        self.subscribers: dict[web.WebSocketResponse, asyncio.Queue[str]] = {}
        self._early_messages: deque[str] = deque(maxlen=20_000)
        self._snapshot_dirty = False
        self._stop = asyncio.Event()
        self._upstream_task: asyncio.Task | None = None
        self._refresh_task: asyncio.Task | None = None
        self._persist_task: asyncio.Task | None = None
        self._rest_retry_after = 0.0
        self._rest_backoff = 30.0
        self._message_count = 0
        self._closed_candle_count = 0

    @property
    def upstream_url(self) -> str:
        names: list[str] = []
        for symbol in SYMBOLS:
            lower = symbol.lower()
            names.extend(f"{lower}@kline_{interval}" for interval in INTERVALS)
            names.append(f"{lower}@ticker")
        return f"{self.ws_base}?streams={'/'.join(names)}"

    def load_persisted_snapshot(self) -> bool:
        try:
            payload = json.loads(self.snapshot_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        if not _snapshot_is_valid(payload):
            LOG.warning("persisted snapshot rejected; a fresh REST bootstrap is required")
            return False
        self.snapshot = payload
        LOG.info(
            "snapshot loaded from disk generated_at_ms=%s symbols=%d",
            payload.get("generated_at_ms"),
            _int(payload.get("symbol_count")),
        )
        return True

    async def start(self) -> None:
        self.load_persisted_snapshot()
        self._upstream_task = asyncio.create_task(self.run_upstream(), name="binance-upstream-ws")
        self._refresh_task = asyncio.create_task(self.refresh_loop(), name="binance-snapshot-refresh")
        self._persist_task = asyncio.create_task(self.persist_loop(), name="binance-snapshot-persist")

    async def stop(self) -> None:
        self._stop.set()
        tasks = [task for task in (self._upstream_task, self._refresh_task, self._persist_task) if task]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await self.persist_snapshot()

    async def run_upstream(self) -> None:
        backoff = 2.0
        first_connection = True
        while not self._stop.is_set():
            try:
                async with websockets.connect(
                    self.upstream_url,
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=5,
                    max_size=4 * 1024 * 1024,
                ) as upstream:
                    self.upstream_connected = True
                    self.last_error = None
                    if not first_connection:
                        LOG.warning("Binance upstream WebSocket reconnected")
                    else:
                        LOG.info(
                            "Binance upstream WebSocket connected streams=%d",
                            len(SYMBOLS) * (len(INTERVALS) + 1),
                        )
                    first_connection = False
                    backoff = 2.0
                    async for message in upstream:
                        if self._stop.is_set():
                            break
                        await self.handle_upstream_message(message)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"
                LOG.warning("Binance upstream WebSocket disconnected error=%s", self.last_error)
                await asyncio.sleep(backoff)
                backoff = min(60.0, backoff * 2.0)
            finally:
                self.upstream_connected = False

    async def handle_upstream_message(self, message: str | bytes) -> None:
        text = message.decode("utf-8", errors="replace") if isinstance(message, bytes) else str(message)
        self.last_event_at = time.time()
        self._message_count += 1
        if self.snapshot is None:
            self._early_messages.append(text)
            return
        self._apply_market_event(text)
        self._broadcast(text)

    def _apply_market_event(self, message: str) -> None:
        if self.snapshot is None:
            return
        try:
            raw = json.loads(message)
        except json.JSONDecodeError:
            return
        payload = raw.get("data", raw) if isinstance(raw, Mapping) else raw
        if not isinstance(payload, Mapping):
            return
        event_type = str(payload.get("e") or "")
        symbol = str(payload.get("s") or "").upper()
        if symbol not in self.snapshot["symbols"]:
            return
        target = self.snapshot["symbols"][symbol]
        now_ms = int(time.time() * 1000)
        if event_type == "24hrTicker":
            target["ticker"] = {
                "symbol": symbol,
                "lastPrice": payload.get("c"),
                "bidPrice": payload.get("b"),
                "askPrice": payload.get("a"),
                "quoteVolume": payload.get("q"),
                "priceChangePercent": payload.get("P"),
                "_relay_event_time_ms": _int(payload.get("E"), now_ms),
                "_relay_transport": "WEBSOCKET",
            }
            return
        if event_type != "kline":
            return
        kline = payload.get("k")
        if not isinstance(kline, Mapping):
            return
        interval = str(kline.get("i") or "")
        if interval not in INTERVALS or not bool(kline.get("x")):
            return
        open_time = _int(kline.get("t"))
        close_time = _int(kline.get("T"))
        if open_time <= 0 or close_time >= now_ms:
            return
        row = {
            "open_time": open_time,
            "open": str(kline.get("o", "0")),
            "high": str(kline.get("h", "0")),
            "low": str(kline.get("l", "0")),
            "close": str(kline.get("c", "0")),
            "volume": str(kline.get("v", "0")),
            "close_time": close_time,
            "quote_volume": str(kline.get("q", "0")),
            "trade_count": _int(kline.get("n")),
            "taker_buy_base_volume": str(kline.get("V", "0")),
            "taker_buy_quote_volume": str(kline.get("Q", "0")),
            "_relay_transport": "WEBSOCKET",
        }
        rows = target["klines"][interval]
        by_time = {
            _int(item.get("open_time")): dict(item)
            for item in rows
            if isinstance(item, Mapping)
        }
        by_time[open_time] = row
        cap = int(RELAY_HISTORY_LIMITS[interval])
        target["klines"][interval] = [by_time[key] for key in sorted(by_time)][-cap:]
        self.snapshot["generated_at_ms"] = now_ms
        self.snapshot["generated_at"] = _utc_iso(now_ms)
        self._snapshot_dirty = True
        self._closed_candle_count += 1

    def _apply_early_messages(self) -> None:
        buffered = list(self._early_messages)
        self._early_messages.clear()
        for message in buffered:
            self._apply_market_event(message)

    def _merge_rest_snapshot(self, fresh: dict[str, Any]) -> None:
        """Repair historical gaps without overwriting newer live observations."""
        old = self.snapshot
        now_ms = int(time.time() * 1000)
        if old is not None:
            for symbol in SYMBOLS:
                old_item = old.get("symbols", {}).get(symbol, {})
                new_item = fresh["symbols"][symbol]
                old_ticker = old_item.get("ticker", {}) if isinstance(old_item, Mapping) else {}
                if isinstance(old_ticker, Mapping) and old_ticker.get("_relay_transport") == "WEBSOCKET":
                    new_item["ticker"] = dict(old_ticker)
                old_klines = old_item.get("klines", {}) if isinstance(old_item, Mapping) else {}
                for interval in INTERVALS:
                    old_rows = old_klines.get(interval, []) if isinstance(old_klines, Mapping) else []
                    fresh_rows = new_item["klines"][interval]
                    combined = {_int(row.get("open_time")): dict(row) for row in fresh_rows}
                    for row in old_rows if isinstance(old_rows, list) else []:
                        if not isinstance(row, Mapping) or row.get("_relay_transport") != "WEBSOCKET":
                            continue
                        key = _int(row.get("open_time"))
                        if key > 0:
                            combined[key] = dict(row)
                    new_item["klines"][interval] = [
                        combined[key] for key in sorted(combined)
                    ][-int(RELAY_HISTORY_LIMITS[interval]):]
        fresh["generated_at_ms"] = max(now_ms, _int(fresh.get("generated_at_ms")))
        fresh["generated_at"] = _utc_iso(_int(fresh["generated_at_ms"]))
        self.snapshot = fresh
        self._apply_early_messages()
        self._snapshot_dirty = True

    def _broadcast(self, message: str) -> None:
        for websocket, queue in list(self.subscribers.items()):
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                self.subscribers.pop(websocket, None)
                asyncio.create_task(websocket.close(code=1013, message=b"consumer too slow"))

    def compact_bootstrap_message(self) -> str:
        if self.snapshot is None:
            raise RuntimeError("snapshot not ready")
        return json.dumps(
            {"type": "snapshot", "snapshot": compact_snapshot(self.snapshot)},
            separators=(",", ":"),
        )

    async def refresh_loop(self) -> None:
        while not self._stop.is_set():
            now = time.time()
            snapshot_ms = _int((self.snapshot or {}).get("generated_at_ms"))
            snapshot_age = max(0.0, now - snapshot_ms / 1000.0) if snapshot_ms > 0 else float("inf")
            if self.snapshot is None or snapshot_age > REST_REFRESH_AFTER_SECONDS:
                if now >= self._rest_retry_after:
                    try:
                        fresh = await asyncio.to_thread(fetch_snapshot)
                        if not _snapshot_is_valid(fresh):
                            raise RelayError("fetched REST snapshot failed validation")
                        self._merge_rest_snapshot(fresh)
                        LOG.info(
                            "REST bootstrap refreshed symbols=%d age_before_refresh=%.1fs",
                            len(fresh["symbols"]),
                            snapshot_age,
                        )
                        self.last_refresh_error = None
                        self._rest_backoff = 30.0
                        await self.persist_snapshot()
                        self._broadcast(self.compact_bootstrap_message())
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        self.last_refresh_error = f"{type(exc).__name__}: {exc}"
                        LOG.error("REST bootstrap refresh failed: %s", self.last_refresh_error)
                        delay = 3600.0 if "418" in self.last_refresh_error else min(900.0, self._rest_backoff)
                        self._rest_retry_after = time.time() + delay
                        self._rest_backoff = min(900.0, self._rest_backoff * 2.0)
            await asyncio.sleep(30.0)

    async def persist_loop(self) -> None:
        while not self._stop.is_set():
            await asyncio.sleep(PERSIST_INTERVAL_SECONDS)
            if self._snapshot_dirty:
                await self.persist_snapshot()

    async def persist_snapshot(self) -> None:
        if self.snapshot is None:
            return
        payload = copy.deepcopy(self.snapshot)
        try:
            await asyncio.to_thread(self._write_snapshot_atomic, payload)
            self._snapshot_dirty = False
        except OSError as exc:
            LOG.error("snapshot persistence failed: %s", exc)

    def _write_snapshot_atomic(self, payload: dict[str, Any]) -> None:
        self.snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.snapshot_path.with_suffix(self.snapshot_path.suffix + ".tmp")
        temp.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
        os.replace(temp, self.snapshot_path)

    def health_payload(self) -> dict[str, Any]:
        now = time.time()
        last_event_age = None if self.last_event_at is None else round(max(0.0, now - self.last_event_at), 3)
        snapshot_ms = _int((self.snapshot or {}).get("generated_at_ms"))
        snapshot_age = None if snapshot_ms <= 0 else round(max(0.0, now - snapshot_ms / 1000.0), 3)
        return {
            "service": "binance-market-data-relay",
            "snapshot_ready": self.snapshot is not None,
            "upstream_connected": self.upstream_connected,
            "upstream_healthy": bool(
                self.upstream_connected and last_event_age is not None and last_event_age <= EVENT_STALE_AFTER_SECONDS
            ),
            "symbols": len(SYMBOLS),
            "intervals": list(INTERVALS),
            "upstream_stream_count": len(SYMBOLS) * (len(INTERVALS) + 1),
            "last_event_age_seconds": last_event_age,
            "snapshot_age_seconds": snapshot_age,
            "subscriber_count": len(self.subscribers),
            "events_total": self._message_count,
            "closed_candles_total": self._closed_candle_count,
            "last_error": self.last_error,
            "last_refresh_error": self.last_refresh_error,
        }


async def health_handler(request: web.Request) -> web.Response:
    state: RelayState = request.app["relay_state"]
    return web.json_response(state.health_payload(), status=200)


async def snapshot_handler(request: web.Request) -> web.Response:
    state: RelayState = request.app["relay_state"]
    if not authorized(request.headers.get("Authorization"), state.token):
        return web.json_response({"error": "unauthorized"}, status=401)
    if state.snapshot is None:
        return web.json_response({"error": "snapshot_not_ready"}, status=503)
    try:
        return web.json_response(compact_snapshot(state.snapshot))
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=503)


async def stream_handler(request: web.Request) -> web.StreamResponse:
    state: RelayState = request.app["relay_state"]
    if not authorized(request.headers.get("Authorization"), state.token):
        return web.json_response({"error": "unauthorized"}, status=401)
    if state.snapshot is None:
        return web.json_response({"error": "snapshot_not_ready"}, status=503)
    websocket = web.WebSocketResponse(heartbeat=20.0, max_msg_size=4 * 1024 * 1024)
    await websocket.prepare(request)
    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=512)
    state.subscribers[websocket] = queue
    sender: asyncio.Task | None = None
    try:
        await websocket.send_str(state.compact_bootstrap_message())

        async def send_pending() -> None:
            while not websocket.closed:
                message = await queue.get()
                await websocket.send_str(message)

        sender = asyncio.create_task(send_pending(), name="relay-subscriber-sender")
        async for message in websocket:
            if message.type == WSMsgType.ERROR:
                LOG.warning("downstream WebSocket error: %s", websocket.exception())
    finally:
        state.subscribers.pop(websocket, None)
        if sender is not None:
            sender.cancel()
            await asyncio.gather(sender, return_exceptions=True)
        if not websocket.closed:
            await websocket.close()
    return websocket


async def _startup(app: web.Application) -> None:
    await app["relay_state"].start()


async def _cleanup(app: web.Application) -> None:
    await app["relay_state"].stop()


def create_app(*, token: str | None = None, snapshot_path: str | Path | None = None) -> web.Application:
    resolved_token = token if token is not None else os.getenv("RELAY_SHARED_TOKEN", "")
    resolved_path = snapshot_path if snapshot_path is not None else os.getenv(
        "RELAY_SNAPSHOT_PATH", "/data/latest-market-data.json"
    )
    state = RelayState(token=resolved_token, snapshot_path=resolved_path)
    app = web.Application(client_max_size=1024 * 1024)
    app["relay_state"] = state
    app.router.add_get("/healthz", health_handler)
    app.router.add_get("/health", health_handler)
    app.router.add_get("/snapshot", snapshot_handler)
    app.router.add_get("/stream", stream_handler)
    app.on_startup.append(_startup)
    app.on_cleanup.append(_cleanup)
    return app


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    port = int(os.getenv("PORT", "8080"))
    web.run_app(create_app(), host="0.0.0.0", port=port, print=None)


if __name__ == "__main__":
    main()
