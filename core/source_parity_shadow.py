"""Diagnostic-only source parity measurements for Paper Trading.

This module compares an already selected market-data source with the local
Binance WebSocket reference using the same indicator primitives that feed the
entry strategy. It does not approve, reject, score, or alter a trade.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from dual_mode_strategy import (
    _closed_candles,
    _volume_ratio,
    bullish_pattern,
    calculate_atr,
    calculate_bollinger,
    calculate_ema,
    calculate_rsi,
)


def _num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _delta(source: Any, reference: Any) -> float | None:
    source_value = _num(source)
    reference_value = _num(reference)
    if source_value is None or reference_value is None:
        return None
    return source_value - reference_value


def _pct_delta(source: Any, reference: Any) -> float | None:
    source_value = _num(source)
    reference_value = _num(reference)
    if source_value is None or reference_value in (None, 0.0):
        return None
    return (source_value - reference_value) / abs(reference_value) * 100.0


def _feature_snapshot(
    ticker: Mapping[str, Any],
    candles_15m: Iterable[Mapping[str, Any]],
    candles_5m: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    closed_15m = _closed_candles(list(candles_15m))
    closed_5m = _closed_candles(list(candles_5m))
    if len(closed_15m) < 100 or len(closed_5m) < 4:
        return {
            "available": False,
            "closed_15m_count": len(closed_15m),
            "closed_5m_count": len(closed_5m),
        }

    price = float(ticker.get("lastPrice", 0.0) or 0.0)
    p15 = [row["close"] for row in closed_15m]
    p5 = [row["close"] for row in closed_5m]
    ema100 = calculate_ema(p15)
    rsi15 = calculate_rsi(p15)
    rsi5 = calculate_rsi(p5)
    atr15 = calculate_atr(closed_15m)
    atr5 = calculate_atr(closed_5m)
    lower15, middle15, upper15 = calculate_bollinger(closed_15m)
    lower5, middle5, upper5 = calculate_bollinger(closed_5m)
    volume15 = _volume_ratio(closed_15m)
    volume5 = _volume_ratio(closed_5m)
    found, pattern, confirmed = bullish_pattern(closed_5m)

    return {
        "available": True,
        "closed_15m_count": len(closed_15m),
        "closed_5m_count": len(closed_5m),
        "price": price,
        "ema100": ema100,
        "rsi15m": rsi15,
        "rsi5m": rsi5,
        "atr15m": atr15,
        "atr5m": atr5,
        "lower_band_15m": lower15,
        "middle_band_15m": middle15,
        "upper_band_15m": upper15,
        "lower_band_5m": lower5,
        "middle_band_5m": middle5,
        "upper_band_5m": upper5,
        "volume_ratio_15m": volume15,
        "volume_ratio_5m": volume5,
        "pattern": pattern,
        "pattern_confirmed": confirmed,
        "pattern_found": found,
    }


def build_source_parity_shadow(
    *,
    source_ticker: Mapping[str, Any],
    source_15m_candles: Iterable[Mapping[str, Any]],
    source_5m_candles: Iterable[Mapping[str, Any]],
    binance_ticker: Mapping[str, Any] | None,
    binance_15m_candles: Iterable[Mapping[str, Any]],
    binance_5m_candles: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Compare source features against Binance without changing entry behavior."""
    source = _feature_snapshot(source_ticker, source_15m_candles, source_5m_candles)
    reference = _feature_snapshot(
        binance_ticker or {},
        binance_15m_candles,
        binance_5m_candles,
    )

    result: dict[str, Any] = {
        "schema_version": 1,
        "diagnostic_only": True,
        "source": "BYBIT",
        "reference": "BINANCE_WS",
        "status": "READY" if source.get("available") and reference.get("available") else "INSUFFICIENT_REFERENCE_DATA",
        "source_features": source,
        "binance_reference_features": reference,
    }
    if not source.get("available") or not reference.get("available"):
        return result

    numeric_fields = (
        "price",
        "ema100",
        "rsi15m",
        "rsi5m",
        "atr15m",
        "atr5m",
        "lower_band_15m",
        "middle_band_15m",
        "upper_band_15m",
        "lower_band_5m",
        "middle_band_5m",
        "upper_band_5m",
        "volume_ratio_15m",
        "volume_ratio_5m",
    )
    result["numeric_delta_source_minus_binance"] = {
        field: _delta(source.get(field), reference.get(field))
        for field in numeric_fields
    }
    result["numeric_delta_percent_vs_binance"] = {
        field: _pct_delta(source.get(field), reference.get(field))
        for field in numeric_fields
    }
    result["categorical_comparison"] = {
        "pattern_match": source.get("pattern") == reference.get("pattern"),
        "pattern_confirmed_match": source.get("pattern_confirmed") == reference.get("pattern_confirmed"),
        "pattern_source": source.get("pattern"),
        "pattern_binance": reference.get("pattern"),
        "pattern_confirmed_source": source.get("pattern_confirmed"),
        "pattern_confirmed_binance": reference.get("pattern_confirmed"),
    }
    return result


__all__ = ["build_source_parity_shadow"]
