from __future__ import annotations

import time
from typing import Any


_VALID_STATES = {"FRESH", "RECENT", "STALE", "UNKNOWN"}


def audit_5m_entry_freshness(
    *,
    candles_5m: list[dict[str, Any]],
    captured_at: float | None = None,
    cache_timestamp: float | None = None,
    cache_ttl_seconds: float | None = None,
) -> dict[str, Any]:
    """Return diagnostic-only freshness metadata for a 5m strategy snapshot.

    This function never changes candles or trading decisions. It identifies the
    candle actually eligible for closed-candle strategy calculations and, when
    a cache timestamp is available, measures snapshot age independently from
    candle age.
    """
    now = float(captured_at if captured_at is not None else time.time())
    result: dict[str, Any] = {
        "available": False,
        "state": "UNKNOWN",
        "captured_at": now,
        "raw_candle_count": len(candles_5m),
        "latest_raw_open_time_ms": None,
        "latest_raw_close_time_ms": None,
        "decision_candle_open_time_ms": None,
        "decision_candle_close_time_ms": None,
        "decision_candle_age_seconds": None,
        "latest_raw_candle_open": False,
        "cache_timestamp": cache_timestamp,
        "cache_age_seconds": None,
        "cache_ttl_seconds": cache_ttl_seconds,
        "cache_expired": None,
    }
    if not candles_5m:
        return result

    latest = candles_5m[-1]
    latest_open = latest.get("open_time")
    latest_close = latest.get("close_time")
    result["latest_raw_open_time_ms"] = latest_open
    result["latest_raw_close_time_ms"] = latest_close

    latest_is_open = False
    if latest_close is not None:
        try:
            latest_is_open = now * 1000.0 <= float(latest_close)
        except (TypeError, ValueError):
            latest_is_open = False
    result["latest_raw_candle_open"] = latest_is_open

    # Strategy currently uses candles_5m[:-1], therefore the decision candle is
    # the penultimate row when the newest Binance candle is still open. If the
    # newest row is already closed, it is itself eligible.
    if latest_is_open and len(candles_5m) >= 2:
        decision = candles_5m[-2]
    else:
        decision = latest

    decision_open = decision.get("open_time")
    decision_close = decision.get("close_time")
    result["decision_candle_open_time_ms"] = decision_open
    result["decision_candle_close_time_ms"] = decision_close
    if decision_close is not None:
        try:
            result["decision_candle_age_seconds"] = round(max(0.0, now - float(decision_close) / 1000.0), 3)
        except (TypeError, ValueError):
            pass

    if cache_timestamp is not None:
        age = max(0.0, now - float(cache_timestamp))
        result["cache_age_seconds"] = round(age, 3)
        if cache_ttl_seconds is not None:
            result["cache_expired"] = age >= float(cache_ttl_seconds)

    if decision_close is None:
        result["state"] = "UNKNOWN"
    elif result["cache_expired"] is True:
        result["state"] = "STALE"
    elif result["decision_candle_age_seconds"] is not None and result["decision_candle_age_seconds"] <= 90.0:
        result["state"] = "FRESH"
    elif result["decision_candle_age_seconds"] <= 330.0:
        result["state"] = "RECENT"
    else:
        result["state"] = "STALE"

    result["available"] = result["state"] in _VALID_STATES
    return result
