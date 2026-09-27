"""Execution-venue alignment gate for Paper entries.

The strategy may use a fallback public-data venue (currently Bybit) when
Binance REST is rate-limited, but Paper execution is intended to emulate
Binance Spot. A fallback signal is therefore eligible only when the Binance
public WebSocket reference confirms the same market state.
"""
from __future__ import annotations

import time
from typing import Any, Iterable, Mapping


DEFAULT_MAX_PRICE_DIVERGENCE_PERCENT = 0.50
DEFAULT_MAX_CANDLE_DIVERGENCE_PERCENT = 0.75
DEFAULT_BINANCE_TICKER_MAX_AGE_SECONDS = 20.0
CANDLE_INTERVAL_SECONDS = {"5m": 300.0, "15m": 900.0}


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _direction(candle: Mapping[str, Any] | None) -> str:
    if not isinstance(candle, Mapping):
        return "UNKNOWN"
    open_price = _number(candle.get("open"))
    close_price = _number(candle.get("close"))
    if open_price is None or close_price is None or open_price <= 0:
        return "UNKNOWN"
    tolerance = open_price * 0.00005
    delta = close_price - open_price
    if abs(delta) <= tolerance:
        return "FLAT"
    return "BULLISH" if delta > 0 else "BEARISH"


def _latest_closed(candles: Iterable[Mapping[str, Any]] | None, now: float) -> dict[str, Any] | None:
    if not candles:
        return None
    now_ms = now * 1000.0
    candidates: list[Mapping[str, Any]] = []
    for candle in candles:
        if not isinstance(candle, Mapping):
            continue
        open_time = _number(candle.get("open_time"))
        close_time = _number(candle.get("close_time"))
        if open_time is None or close_time is None:
            continue
        if close_time < now_ms:
            candidates.append(candle)
    if not candidates:
        return None
    latest = max(candidates, key=lambda item: _number(item.get("open_time")) or 0.0)
    return dict(latest)


def _relative_diff(left: Any, right: Any) -> float | None:
    left_value = _number(left)
    right_value = _number(right)
    if left_value is None or right_value is None:
        return None
    denominator = max(abs(right_value), 1e-12)
    return abs(left_value - right_value) / denominator * 100.0


def _candle_compare(
    source_candle: Mapping[str, Any] | None,
    binance_candle: Mapping[str, Any] | None,
    *,
    interval: str,
    now: float,
    max_divergence_percent: float,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "interval": interval,
        "aligned": False,
        "reason": "UNAVAILABLE",
        "source_direction": _direction(source_candle),
        "binance_direction": _direction(binance_candle),
    }
    if not isinstance(source_candle, Mapping) or not isinstance(binance_candle, Mapping):
        return result

    source_open_time = _number(source_candle.get("open_time"))
    binance_open_time = _number(binance_candle.get("open_time"))
    if source_open_time is None or binance_open_time is None:
        result["reason"] = "MISSING_OPEN_TIME"
        return result

    if abs(source_open_time - binance_open_time) > 1000.0:
        result["reason"] = "OPEN_TIME_MISMATCH"
        result["source_open_time"] = int(source_open_time)
        result["binance_open_time"] = int(binance_open_time)
        return result

    close_time = _number(binance_candle.get("close_time"))
    max_age = CANDLE_INTERVAL_SECONDS.get(interval, 300.0) + 30.0
    age_seconds = None if close_time is None else max(0.0, now - close_time / 1000.0)
    result["age_seconds"] = age_seconds
    if age_seconds is None or age_seconds > max_age:
        result["reason"] = "BINANCE_CLOSED_CANDLE_STALE"
        return result

    fields: dict[str, float] = {}
    for field in ("open", "high", "low", "close"):
        diff = _relative_diff(source_candle.get(field), binance_candle.get(field))
        if diff is None:
            result["reason"] = f"MISSING_{field.upper()}"
            result["field_divergence_percent"] = fields
            return result
        fields[field] = round(diff, 6)

    result["field_divergence_percent"] = fields
    result["max_field_divergence_percent"] = round(max(fields.values()), 6)

    source_direction = result["source_direction"]
    binance_direction = result["binance_direction"]
    if source_direction == "UNKNOWN" or binance_direction == "UNKNOWN":
        result["reason"] = "DIRECTION_UNAVAILABLE"
        return result
    if source_direction != binance_direction:
        result["reason"] = "CANDLE_DIRECTION_MISMATCH"
        return result
    if result["max_field_divergence_percent"] > max_divergence_percent:
        result["reason"] = "CANDLE_OHLC_DIVERGENCE"
        return result

    result["aligned"] = True
    result["reason"] = "MATCH"
    return result


def assess_execution_market_alignment(
    *,
    market_data_source: str,
    source_ticker: Mapping[str, Any] | None,
    source_5m_candles: Iterable[Mapping[str, Any]] | None,
    source_15m_candles: Iterable[Mapping[str, Any]] | None,
    binance_ticker: Mapping[str, Any] | None,
    binance_5m_closed: Mapping[str, Any] | None,
    binance_15m_closed: Mapping[str, Any] | None,
    binance_stream_healthy: bool,
    now: float | None = None,
    max_price_divergence_percent: float = DEFAULT_MAX_PRICE_DIVERGENCE_PERCENT,
    max_candle_divergence_percent: float = DEFAULT_MAX_CANDLE_DIVERGENCE_PERCENT,
    max_binance_ticker_age_seconds: float = DEFAULT_BINANCE_TICKER_MAX_AGE_SECONDS,
) -> dict[str, Any]:
    """Return whether the candidate is safe to execute against Binance Spot."""
    current = time.time() if now is None else float(now)
    source = str(market_data_source or "UNKNOWN").upper()

    if source == "BINANCE":
        return {
            "schema_version": 1,
            "eligible": True,
            "status": "SAME_EXECUTION_VENUE",
            "market_data_source": "BINANCE",
            "execution_reference_source": "BINANCE",
            "reason": "SIGNAL_AND_EXECUTION_SAME_VENUE",
        }

    result: dict[str, Any] = {
        "schema_version": 1,
        "eligible": False,
        "status": "MISMATCH",
        "market_data_source": source,
        "execution_reference_source": "BINANCE",
        "max_price_divergence_percent": max_price_divergence_percent,
        "max_candle_divergence_percent": max_candle_divergence_percent,
        "binance_stream_healthy": bool(binance_stream_healthy),
    }

    if source != "BYBIT":
        result["reason"] = "UNSUPPORTED_SIGNAL_SOURCE"
        return result

    if not binance_stream_healthy:
        result["reason"] = "BINANCE_REFERENCE_STREAM_UNHEALTHY"
        return result

    if not isinstance(binance_ticker, Mapping):
        result["reason"] = "BINANCE_REFERENCE_TICKER_MISSING"
        return result

    binance_price = _number(binance_ticker.get("lastPrice"))
    source_price = _number((source_ticker or {}).get("lastPrice"))
    ticker_age = _number(binance_ticker.get("received_at"))
    if binance_price is None or binance_price <= 0 or source_price is None or source_price <= 0:
        result["reason"] = "INVALID_EXECUTION_REFERENCE_PRICE"
        return result
    if ticker_age is None or current - ticker_age > max_binance_ticker_age_seconds:
        result["reason"] = "BINANCE_REFERENCE_TICKER_STALE"
        result["ticker_age_seconds"] = None if ticker_age is None else round(max(0.0, current - ticker_age), 3)
        return result

    price_divergence = _relative_diff(source_price, binance_price)
    result["price_divergence_percent"] = round(price_divergence or 0.0, 6)
    result["source_price"] = source_price
    result["binance_execution_price"] = binance_price
    result["binance_ticker_age_seconds"] = round(max(0.0, current - ticker_age), 3)
    if price_divergence is None or price_divergence > max_price_divergence_percent:
        result["reason"] = "PRICE_DIVERGENCE"
        return result

    source_5m = _latest_closed(source_5m_candles, current)
    source_15m = _latest_closed(source_15m_candles, current)
    five = _candle_compare(
        source_5m,
        binance_5m_closed,
        interval="5m",
        now=current,
        max_divergence_percent=max_candle_divergence_percent,
    )
    fifteen = _candle_compare(
        source_15m,
        binance_15m_closed,
        interval="15m",
        now=current,
        max_divergence_percent=max_candle_divergence_percent,
    )
    result["candle_5m"] = five
    result["candle_15m"] = fifteen

    if not five["aligned"]:
        result["reason"] = f"5M_{five['reason']}"
        return result
    if not fifteen["aligned"]:
        result["reason"] = f"15M_{fifteen['reason']}"
        return result

    result["eligible"] = True
    result["status"] = "ALIGNED"
    result["reason"] = "BINANCE_SPOT_STATE_CONFIRMED"
    return result


__all__ = [
    "DEFAULT_BINANCE_TICKER_MAX_AGE_SECONDS",
    "DEFAULT_MAX_CANDLE_DIVERGENCE_PERCENT",
    "DEFAULT_MAX_PRICE_DIVERGENCE_PERCENT",
    "assess_execution_market_alignment",
]
