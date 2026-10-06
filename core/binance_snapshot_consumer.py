"""Opt-in consumer for the GitHub-published Binance Paper market snapshot.

This module only hydrates the existing MarketDataManager cache. It does not
change strategy, scoring, Brain, risk, Trade Manager, or execution policy.
The existing Binance WebSocket remains responsible for live updates.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any, Iterable


class BinanceSnapshotError(RuntimeError):
    pass


DEFAULT_TIMEOUT_SECONDS = 20.0
DEFAULT_MAX_STALE_SECONDS = 900.0
SUPPORTED_INTERVALS = ("5m", "15m", "1h", "4h")
DEFAULT_LIMITS = {"5m": 60, "15m": 150, "1h": 60, "4h": 60}


def _fetch_json(url: str, *, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> dict[str, Any]:
    request = urllib.request.Request(
        str(url),
        headers={"User-Agent": "shadow-trading-bot-binance-snapshot-consumer/1.0"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=float(timeout)) as response:
            payload = json.load(response)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise BinanceSnapshotError(f"snapshot fetch failed: {exc}") from exc
    if not isinstance(payload, dict):
        raise BinanceSnapshotError("snapshot payload is not an object")
    return payload


def _normalise_candle(row: dict[str, Any]) -> dict[str, Any]:
    try:
        return {
            "open_time": int(row["open_time"]),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row["volume"]),
            "close_time": int(row["close_time"]),
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise BinanceSnapshotError("invalid kline row in snapshot") from exc


def _validate_snapshot(
    snapshot: dict[str, Any],
    expected_symbols: Iterable[str],
    *,
    now: float,
    max_stale_seconds: float,
) -> tuple[dict[str, Any], float]:
    if int(snapshot.get("schema_version", 0)) != 1:
        raise BinanceSnapshotError("unsupported snapshot schema")
    if str(snapshot.get("source", "")) != "binance_spot_public_rest":
        raise BinanceSnapshotError("unexpected snapshot source")

    try:
        generated_at_ms = int(snapshot["generated_at_ms"])
    except (KeyError, TypeError, ValueError) as exc:
        raise BinanceSnapshotError("missing generated_at_ms") from exc

    generated_at = generated_at_ms / 1000.0
    age = now - generated_at
    if age < -30.0:
        raise BinanceSnapshotError("snapshot timestamp is unexpectedly in the future")
    if age > float(max_stale_seconds):
        raise BinanceSnapshotError(
            f"snapshot is too stale: age={age:.1f}s max={max_stale_seconds:.1f}s"
        )

    expected = {str(symbol).upper() for symbol in expected_symbols}
    symbols = snapshot.get("symbols")
    if not isinstance(symbols, dict) or set(symbols) != expected:
        raise BinanceSnapshotError("snapshot symbol coverage does not match the configured universe")
    if int(snapshot.get("symbol_count", -1)) != len(expected):
        raise BinanceSnapshotError("snapshot symbol_count mismatch")

    for symbol in sorted(expected):
        payload = symbols.get(symbol)
        if not isinstance(payload, dict):
            raise BinanceSnapshotError(f"{symbol} payload is invalid")
        klines = payload.get("klines")
        if not isinstance(klines, dict):
            raise BinanceSnapshotError(f"{symbol} klines container is invalid")
        for interval in SUPPORTED_INTERVALS:
            rows = klines.get(interval)
            if not isinstance(rows, list) or not rows:
                raise BinanceSnapshotError(f"{symbol} {interval} has no candles")
            previous = -1
            for row in rows:
                if not isinstance(row, dict):
                    raise BinanceSnapshotError(f"{symbol} {interval} contains an invalid row")
                candle = _normalise_candle(row)
                if candle["open_time"] <= previous:
                    raise BinanceSnapshotError(f"{symbol} {interval} is not strictly chronological")
                if candle["close_time"] >= int(now * 1000):
                    raise BinanceSnapshotError(f"{symbol} {interval} contains an unclosed candle")
                previous = candle["open_time"]
    return symbols, generated_at


def hydrate_market_data_manager(
    manager: Any,
    snapshot_url: str,
    expected_symbols: Iterable[str],
    *,
    now: float | None = None,
    max_stale_seconds: float = DEFAULT_MAX_STALE_SECONDS,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    persist: bool = True,
) -> dict[str, Any]:
    """Fetch and seed the existing cache; fail closed on malformed/stale data."""
    if not str(snapshot_url).strip():
        return {"enabled": False, "loaded": False, "reason": "URL_NOT_CONFIGURED"}

    current = time.time() if now is None else float(now)
    snapshot = _fetch_json(snapshot_url, timeout=timeout)
    symbols, generated_at = _validate_snapshot(
        snapshot,
        expected_symbols,
        now=current,
        max_stale_seconds=max_stale_seconds,
    )

    written = 0
    for symbol in expected_symbols:
        symbol = str(symbol).upper()
        payload = symbols[symbol]

        ticker = payload.get("ticker")
        if not isinstance(ticker, dict):
            raise BinanceSnapshotError(f"{symbol} ticker is invalid")
        manager.cache.put(
            f"ticker:{symbol}",
            dict(ticker),
            fetched_at=generated_at,
            persist=False,
        )
        written += 1

        klines = payload["klines"]
        for interval, limit in DEFAULT_LIMITS.items():
            rows = [_normalise_candle(row) for row in klines[interval]]
            selected = rows[-limit:]
            manager.cache.put(
                f"{interval}:{symbol}:{limit}",
                selected,
                fetched_at=generated_at,
                persist=False,
            )
            written += 1

    if persist:
        manager.cache.flush()

    return {
        "enabled": True,
        "loaded": True,
        "generated_at": generated_at,
        "age_seconds": round(max(0.0, current - generated_at), 3),
        "symbols": len(symbols),
        "cache_entries_written": written,
    }


__all__ = [
    "BinanceSnapshotError",
    "DEFAULT_LIMITS",
    "DEFAULT_MAX_STALE_SECONDS",
    "hydrate_market_data_manager",
]
