"""Counterfactual path tracking for entries blocked by an opt-in Paper trial.

This module models price movement only. It never creates positions, submits
orders, changes a decision, or touches the execution/risk lifecycle.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from copy import deepcopy
from datetime import datetime, timezone
from math import isfinite
from typing import Any

INTERVAL_MS = 5 * 60 * 1000
DEFAULT_MAX_BARS = 24
TRIAL_NAME = "PAPER_TRIAL_MAIN_SCALP_SELLER_PRESSURE"


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if isfinite(result) else None


def _epoch_ms(value: Any) -> int | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return int(parsed.timestamp() * 1000)
    except (TypeError, ValueError, OverflowError):
        return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_blocked_entry_watch(
    capture: Mapping[str, Any],
    *,
    fee_rate: float,
    blocked_reason: str,
    max_bars: int = DEFAULT_MAX_BARS,
) -> dict[str, Any]:
    """Create an immutable start snapshot using only the entry-time capture."""
    capture_id = str(capture.get("capture_id") or "").strip()
    legacy = capture.get("legacy_result")
    legacy = legacy if isinstance(legacy, Mapping) else {}
    scenario = capture.get("entry_scenario")
    scenario = scenario if isinstance(scenario, Mapping) else {}
    risk = scenario.get("risk")
    risk = risk if isinstance(risk, Mapping) else {}
    v2 = capture.get("v2_decision")
    v2 = v2 if isinstance(v2, Mapping) else {}

    entry = _number(legacy.get("price"))
    captured_at = str(capture.get("captured_at") or "").strip()
    captured_at_ms = _epoch_ms(captured_at)
    stop = _number(risk.get("atr_stop_loss"))
    target = _number(risk.get("target_price"))
    if entry is not None and (entry <= 0 or stop is None or stop <= 0 or stop >= entry):
        stop = None
    if entry is not None and (target is None or target <= entry):
        target = None
    fee = _number(fee_rate)
    fee = max(0.0, fee or 0.0)
    max_bars_value = max(1, int(max_bars))

    measurable = bool(capture_id and entry is not None and entry > 0 and captured_at_ms is not None)
    status = "OBSERVING" if measurable else "UNMEASURABLE_CONTEXT"
    last_open = (
        captured_at_ms // INTERVAL_MS * INTERVAL_MS
        if captured_at_ms is not None
        else None
    )
    risk_percent = (
        (entry - stop) / entry * 100.0
        if entry is not None and entry > 0 and stop is not None and 0 < stop < entry
        else None
    )

    return {
        "schema_version": 1,
        "trial_name": TRIAL_NAME,
        "source_capture_id": capture_id or None,
        "symbol": str(capture.get("symbol") or legacy.get("symbol") or "").upper(),
        "trade_mode": str(v2.get("trade_mode") or scenario.get("trade_mode") or "SCALP").upper(),
        "entry_capture_at_utc": captured_at or None,
        "entry_capture_at_ms": captured_at_ms,
        "entry_price": entry,
        "stop_price": stop,
        "target_price": target,
        "stop_source": "ENTRY_V2_ATR_STOP_LOSS" if stop is not None else "UNAVAILABLE",
        "target_source": str(risk.get("target_source") or "ENTRY_V2_TARGET") if target is not None else "UNAVAILABLE",
        "target_status": str(risk.get("target_status") or "UNKNOWN"),
        "expected_reward_risk": _number(risk.get("reward_risk")),
        "risk_percent": risk_percent,
        "fee_rate_per_side": fee,
        "estimated_round_trip_fee_percent": fee * 200.0,
        "score": _number(legacy.get("scalp_score") or legacy.get("score")),
        "entry_v2_failed_gate": str(v2.get("failed_gate") or ""),
        "blocked_reason": str(blocked_reason or ""),
        "path_source": "BINANCE_RELAY_WEBSOCKET_CLOSED_5M_CANDLES",
        "path_model": "ENTRY_V2_ATR_STOP_AND_TARGET",
        "max_bars": max_bars_value,
        "bars_observed": 0,
        "last_processed_open_time_ms": last_open,
        "highest_price_after_entry": entry,
        "lowest_price_after_entry": entry,
        "max_favorable_percent": 0.0 if entry is not None else None,
        "max_adverse_percent": 0.0 if entry is not None else None,
        "status": status,
        "outcome_class": "PENDING" if measurable else "UNMEASURABLE",
        "completed_at_utc": None,
        "exit_reason": None,
        "hypothetical_exit_price": None,
        "gross_return_percent": None,
        "net_return_percent_after_estimated_fees": None,
        "net_r_multiple_after_estimated_fees": None,
        "measurement_caveat": (
            "Price-path counterfactual only; no simulated order fill, spread or slippage. "
            "Levels are the captured Entry v2 ATR stop/target, not a reconstructed Legacy fill."
        ),
    }


def _complete(
    record: dict[str, Any],
    *,
    status: str,
    outcome_class: str,
    reason: str,
    exit_price: float | None = None,
) -> None:
    record["status"] = status
    record["outcome_class"] = outcome_class
    record["exit_reason"] = reason
    record["completed_at_utc"] = _now_iso()
    record["hypothetical_exit_price"] = exit_price
    entry = _number(record.get("entry_price"))
    fee_percent = _number(record.get("estimated_round_trip_fee_percent")) or 0.0
    if entry is None or entry <= 0 or exit_price is None or exit_price <= 0:
        return
    gross = (exit_price - entry) / entry * 100.0
    net = gross - fee_percent
    record["gross_return_percent"] = round(gross, 6)
    record["net_return_percent_after_estimated_fees"] = round(net, 6)
    risk_percent = _number(record.get("risk_percent"))
    record["net_r_multiple_after_estimated_fees"] = (
        round(net / risk_percent, 6)
        if risk_percent is not None and risk_percent > 0
        else None
    )


def advance_blocked_entry_watch(
    watch: Mapping[str, Any],
    candles: Iterable[Mapping[str, Any]],
) -> tuple[dict[str, Any], bool]:
    """Advance a watch over newly closed bars; mark ambiguous/gapped paths."""
    record = deepcopy(dict(watch))
    if str(record.get("status") or "").upper() != "OBSERVING":
        return record, False

    entry = _number(record.get("entry_price"))
    captured_at_ms = _number(record.get("entry_capture_at_ms"))
    last_open = _number(record.get("last_processed_open_time_ms"))
    if entry is None or entry <= 0 or captured_at_ms is None or last_open is None:
        _complete(
            record,
            status="UNMEASURABLE_CONTEXT",
            outcome_class="UNMEASURABLE",
            reason="INVALID_ENTRY_SNAPSHOT",
        )
        return record, True

    stop = _number(record.get("stop_price"))
    target = _number(record.get("target_price"))
    highest = _number(record.get("highest_price_after_entry")) or entry
    lowest = _number(record.get("lowest_price_after_entry")) or entry
    bars_observed = int(record.get("bars_observed") or 0)
    max_bars = max(1, int(record.get("max_bars") or DEFAULT_MAX_BARS))
    changed = False

    ordered = sorted(
        (item for item in candles if isinstance(item, Mapping)),
        key=lambda item: int(_number(item.get("open_time")) or 0),
    )
    for candle in ordered:
        if candle.get("is_closed") is False:
            continue
        open_time = _number(candle.get("open_time"))
        high = _number(candle.get("high"))
        low = _number(candle.get("low"))
        close = _number(candle.get("close"))
        if open_time is None or high is None or low is None or close is None:
            continue
        open_time = int(open_time)
        if open_time <= captured_at_ms or open_time <= last_open:
            continue
        if not (high > 0 and low > 0 and close > 0 and high >= low):
            continue
        if open_time - int(last_open) > INTERVAL_MS:
            _complete(
                record,
                status="DATA_GAP",
                outcome_class="INCOMPLETE_DATA_GAP",
                reason="MISSING_CLOSED_5M_CANDLE",
            )
            record["last_processed_open_time_ms"] = open_time
            return record, True

        highest = max(highest, high)
        lowest = min(lowest, low)
        bars_observed += 1
        last_open = open_time
        record["bars_observed"] = bars_observed
        record["last_processed_open_time_ms"] = last_open
        record["highest_price_after_entry"] = highest
        record["lowest_price_after_entry"] = lowest
        record["max_favorable_percent"] = round(max(0.0, (highest - entry) / entry * 100.0), 6)
        record["max_adverse_percent"] = round(min(0.0, (lowest - entry) / entry * 100.0), 6)
        changed = True

        stop_hit = stop is not None and low <= stop
        target_hit = target is not None and high >= target
        if stop_hit and target_hit:
            _complete(
                record,
                status="AMBIGUOUS_SAME_CANDLE",
                outcome_class="AMBIGUOUS",
                reason="STOP_AND_TARGET_TOUCHED_WITHIN_SAME_5M_CANDLE",
            )
            return record, True
        if stop_hit:
            _complete(
                record,
                status="STOP_HIT",
                outcome_class="STOP",
                reason="ENTRY_V2_ATR_STOP_TOUCHED",
                exit_price=stop,
            )
            return record, True
        if target_hit:
            _complete(
                record,
                status="TARGET_HIT",
                outcome_class="TARGET",
                reason="ENTRY_V2_TARGET_TOUCHED",
                exit_price=target,
            )
            return record, True
        if bars_observed >= max_bars:
            _complete(
                record,
                status="TIME_LIMIT_EXIT",
                outcome_class="TIME_EXIT",
                reason=f"MAX_{max_bars}_CLOSED_5M_BARS_REACHED",
                exit_price=close,
            )
            return record, True

    if changed:
        record["highest_price_after_entry"] = highest
        record["lowest_price_after_entry"] = lowest
    return record, changed


__all__ = [
    "DEFAULT_MAX_BARS",
    "INTERVAL_MS",
    "TRIAL_NAME",
    "advance_blocked_entry_watch",
    "build_blocked_entry_watch",
]
