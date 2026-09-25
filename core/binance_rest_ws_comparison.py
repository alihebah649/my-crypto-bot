"""REST vs WebSocket candle comparison helpers.

This module is diagnostic-only. It does not select a market-data source and it
never participates in strategy, risk, Trade Manager, or execution decisions.
"""

from __future__ import annotations

from math import isclose
from typing import Any, Mapping, Sequence


_OHLCV_FIELDS = ("open", "high", "low", "close", "volume")


def compare_rest_ws_candle(
    rest_candles: Sequence[Mapping[str, Any]],
    ws_candle: Mapping[str, Any] | None,
    *,
    relative_tolerance: float = 1e-12,
    absolute_tolerance: float = 1e-12,
) -> dict[str, Any]:
    """Compare one WS closed candle with the REST candle having the same open time."""
    result: dict[str, Any] = {
        "status": "NO_WS_CLOSED_CANDLE",
        "open_time": None,
        "max_abs_diff": None,
        "fields_match": None,
    }

    if not isinstance(ws_candle, Mapping) or not bool(ws_candle.get("is_closed")):
        return result

    ws_open_time = _as_int(ws_candle.get("open_time"))
    if ws_open_time is None:
        result["status"] = "INVALID_WS_CANDLE"
        return result

    result["open_time"] = ws_open_time
    match = None
    for candle in rest_candles:
        if not isinstance(candle, Mapping):
            continue
        if _as_int(candle.get("open_time")) == ws_open_time:
            match = candle
            break

    if match is None:
        result["status"] = "NO_REST_MATCH"
        return result

    diffs: dict[str, float] = {}
    fields_match = True
    for field in _OHLCV_FIELDS:
        ws_value = _as_float(ws_candle.get(field))
        rest_value = _as_float(match.get(field))
        if ws_value is None or rest_value is None:
            fields_match = False
            continue
        diff = abs(ws_value - rest_value)
        diffs[field] = diff
        if not isclose(
            ws_value,
            rest_value,
            rel_tol=relative_tolerance,
            abs_tol=absolute_tolerance,
        ):
            fields_match = False

    if not diffs:
        result["status"] = "INVALID_VALUES"
        result["fields_match"] = False
        return result

    result["status"] = "MATCH" if fields_match else "DIVERGENCE"
    result["fields_match"] = fields_match
    result["max_abs_diff"] = max(diffs.values())
    result["field_abs_diff"] = diffs
    return result


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
