"""Truthful Paper market-health summary built from the active venue stream.

This is diagnostic-only: it reports scoring and feed freshness without
changing entry decisions, order simulation, risk, or position management.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def _nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def market_data_guard_alert_label(
    *,
    venue_mode: str,
    status_code: Any,
    blocked: bool,
) -> str | None:
    """Label a blocked market-data guard with the provider that owns it."""
    if not blocked:
        return None

    mode = str(venue_mode or "MIXED").strip().upper()
    venue = {
        "OKX_ONLY_LAB": "OKX",
        "BYBIT_ONLY_LAB": "BYBIT",
    }.get(mode, "BINANCE")

    try:
        status = int(status_code) if status_code is not None else None
    except (TypeError, ValueError):
        status = None

    rate_limit_codes = {403, 429} if venue in {"OKX", "BYBIT"} else {418, 429}
    if status in rate_limit_codes:
        return f"{venue} RATE LIMIT {status}"
    return f"{venue} CIRCUIT OPEN"


def build_paper_market_health_summary(
    *,
    scored_symbol_count: int,
    symbol_count: int,
    local_kline_cache_entries: int,
    venue: str,
    websocket_snapshot: Mapping[str, Any] | None,
) -> dict[str, str]:
    """Report active WebSocket coverage separately from the local fallback cache."""
    scored = _nonnegative_int(scored_symbol_count)
    expected_symbols = _nonnegative_int(symbol_count)
    local_cache_entries = _nonnegative_int(local_kline_cache_entries)
    snapshot = websocket_snapshot if isinstance(websocket_snapshot, Mapping) else {}

    available = bool(snapshot.get("available"))
    connected = bool(snapshot.get("connected"))
    event_stream_healthy = bool(snapshot.get("event_stream_healthy"))
    latest_klines = _nonnegative_int(snapshot.get("symbols_with_latest_kline"))
    expected_klines = _nonnegative_int(snapshot.get("expected_kline_streams"))
    latest_tickers = _nonnegative_int(snapshot.get("tickers_with_latest"))
    expected_tickers = _nonnegative_int(snapshot.get("expected_tickers"))
    full_coverage = (
        expected_klines > 0
        and latest_klines >= expected_klines
        and expected_tickers > 0
        and latest_tickers >= expected_tickers
    )
    stream_healthy = (
        available and connected and event_stream_healthy and full_coverage
    )

    if scored <= 0:
        state = "MARKET DATA DOWN"
    elif scored < expected_symbols or not stream_healthy:
        state = "MARKET DATA DEGRADED"
    else:
        state = "MARKET DATA UP"

    details = [f"Scored symbols: {scored}/{expected_symbols}"]
    normalized_venue = str(venue or "UNKNOWN").strip().upper()
    if available:
        transport = str(snapshot.get("transport") or "").strip().upper()
        feed_name = normalized_venue
        if transport:
            feed_name = f"{feed_name} / {transport}"
        feed_state = "HEALTHY" if stream_healthy else "DEGRADED"
        details.append(f"Active WebSocket feed: {feed_name} — {feed_state}")
        details.append(
            f"Kline streams: {latest_klines}/{expected_klines}; "
            f"Tickers: {latest_tickers}/{expected_tickers}"
        )
        age = snapshot.get("last_event_age_seconds")
        if age is not None:
            try:
                details.append(f"Last WebSocket event: {max(0.0, float(age)):.3f}s ago")
            except (TypeError, ValueError):
                pass
    else:
        details.append(f"Active WebSocket feed: {normalized_venue} — UNAVAILABLE")

    # This cache is not the active WebSocket's in-memory candle history. Label
    # it explicitly so a zero here cannot be mistaken for an empty market feed.
    details.append(
        f"Local Kline fallback cache: {local_cache_entries} entries "
        "(separate from active WebSocket history)"
    )
    runtime = snapshot.get("runtime_integration")
    if isinstance(runtime, Mapping):
        history_keys = runtime.get("kline_history_keys")
        history_rows = runtime.get("kline_history_rows")
    else:
        history_keys = snapshot.get("kline_history_keys")
        history_rows = snapshot.get("kline_history_rows")
    if history_keys is not None and history_rows is not None:
        details.append(
            f"WebSocket candle history: {_nonnegative_int(history_keys)} keys / "
            f"{_nonnegative_int(history_rows)} rows"
        )

    return {"state": state, "detail": "\n".join(details)}
