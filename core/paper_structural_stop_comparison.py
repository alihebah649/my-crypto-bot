"""Paired Paper-only counterfactual comparison of captured ATR and structural stops.

The observer consumes the exact stop/target snapshot captured at entry and the
selected venue's closed 5m candles. It never creates a position, mutates a
Paper position, changes a stop, or submits an order.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from copy import deepcopy
from datetime import datetime, timezone
from math import isfinite
from typing import Any

INTERVAL_MS = 5 * 60 * 1000
DEFAULT_MAX_BARS = 288  # 24 hours of closed 5m candles
TRIAL_NAME = "PAPER_STRUCTURAL_STOP_COMPARISON"
_DECISIVE = {"STOP_HIT", "TARGET_HIT", "TIME_LIMIT_EXIT"}
_TERMINAL = _DECISIVE | {"AMBIGUOUS_SAME_CANDLE", "DATA_GAP", "UNMEASURABLE_CONTEXT"}


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if isfinite(result) else None


def _positive(value: Any) -> float | None:
    result = _number(value)
    return result if result is not None and result > 0 else None


def _epoch_ms(value: Any) -> int | None:
    if isinstance(value, (int, float)):
        parsed = _number(value)
        if parsed is None or parsed <= 0:
            return None
        # Entry captures are ISO timestamps; numeric support is defensive.
        return int(parsed if parsed > 10_000_000_000 else parsed * 1000)
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


def _value(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _status_name(position: Any) -> str:
    status = _value(position, "status", "")
    return str(getattr(status, "name", status) or "").upper()


def _path_snapshot(
    *,
    stop_price: float,
    entry_price: float,
    max_bars: int,
) -> dict[str, Any]:
    return {
        "stop_price": stop_price,
        "stop_distance_percent": round((entry_price - stop_price) / entry_price * 100.0, 8),
        "status": "OBSERVING",
        "outcome_class": "PENDING",
        "bars_to_exit": None,
        "exit_reason": None,
        "hypothetical_exit_price": None,
        "gross_return_percent": None,
        "net_return_percent_after_estimated_fees": None,
        "net_r_multiple_after_estimated_fees": None,
    }


def build_structural_stop_comparison_watch(
    capture: Mapping[str, Any],
    position: Any,
    *,
    fee_rate: float,
    venue: str,
    venue_mode: str,
    max_bars: int = DEFAULT_MAX_BARS,
) -> dict[str, Any]:
    """Build paired ATR/structural paths from one exact entry-time capture."""
    if not isinstance(capture, Mapping):
        raise ValueError("ENTRY_CAPTURE_REQUIRED")

    legacy = capture.get("legacy_result")
    legacy = legacy if isinstance(legacy, Mapping) else {}
    scenario = capture.get("entry_scenario")
    scenario = scenario if isinstance(scenario, Mapping) else {}
    risk = scenario.get("risk")
    risk = risk if isinstance(risk, Mapping) else {}
    metadata = _value(position, "entry_metadata", {})
    metadata = metadata if isinstance(metadata, Mapping) else {}

    capture_id = str(capture.get("capture_id") or "").strip()
    position_id = str(_value(position, "position_id", "") or "").strip()
    symbol = str(_value(position, "symbol", "") or capture.get("symbol") or "").strip().upper()
    captured_at = str(capture.get("captured_at") or "").strip()
    captured_at_ms = _epoch_ms(captured_at)
    captured_entry = _positive(legacy.get("price"))
    entry = _positive(_value(position, "entry_price")) or captured_entry
    atr_stop_raw = _positive(risk.get("atr_stop_loss"))
    structural_stop_raw = _positive(risk.get("structural_stop_candidate"))
    target_raw = _positive(risk.get("target_price"))

    if not capture_id or not position_id or not symbol or captured_at_ms is None:
        raise ValueError("ENTRY_OR_POSITION_IDENTITY_UNAVAILABLE")
    if captured_entry is None or entry is None or atr_stop_raw is None:
        raise ValueError("ATR_ENTRY_SNAPSHOT_UNAVAILABLE")
    if structural_stop_raw is None:
        raise ValueError("STRUCTURAL_STOP_CANDIDATE_UNAVAILABLE")
    if target_raw is None:
        raise ValueError("ENTRY_TARGET_UNAVAILABLE")

    # Preserve the captured distances while anchoring both alternatives to the
    # actual Paper fill price. This avoids treating small entry-price variance
    # as a stop-quality effect.
    entry_adjustment = entry - captured_entry
    atr_stop = atr_stop_raw + entry_adjustment
    structural_stop = structural_stop_raw + entry_adjustment
    target = target_raw + entry_adjustment
    if not (0 < atr_stop < entry and 0 < structural_stop < entry and target > entry):
        raise ValueError("INVALID_STOP_OR_TARGET_RELATIVE_TO_PAPER_ENTRY")

    fee = _number(fee_rate)
    fee = max(0.0, fee or 0.0)
    bars = max(1, min(int(max_bars), 2_000))
    mode = str(
        metadata.get("trade_mode")
        or _value(position, "trade_mode", "")
        or scenario.get("trade_mode")
        or "UNKNOWN"
    ).upper()
    if structural_stop < atr_stop:
        classification = "STRUCTURAL_WIDER"
    elif structural_stop > atr_stop:
        classification = "STRUCTURAL_TIGHTER"
    else:
        classification = "SAME_LEVEL"

    return {
        "schema_version": 1,
        "trial_name": TRIAL_NAME,
        "record_type": "START",
        "record_id": f"{position_id}:START",
        "capture_id": f"{position_id}:START",
        "position_id": position_id,
        "source_capture_id": capture_id,
        "symbol": symbol,
        "venue": str(venue or "UNKNOWN").upper(),
        "venue_mode": str(venue_mode or "UNKNOWN").upper(),
        "trade_mode": mode,
        "mode": "PAPER_ONLY",
        "entry_capture_at_utc": captured_at,
        "entry_capture_at_ms": captured_at_ms,
        "captured_entry_price": captured_entry,
        "entry_price": entry,
        "entry_price_adjustment": round(entry_adjustment, 12),
        "target_price": target,
        "target_source": str(risk.get("target_source") or "ENTRY_V2_CAPTURE"),
        "target_status": str(risk.get("target_status") or "UNKNOWN").upper(),
        "expected_reward_risk_at_capture": _number(risk.get("reward_risk")),
        "fee_rate_per_side": fee,
        "estimated_round_trip_fee_percent": round(fee * 200.0, 8),
        "path_source": f"{str(venue or 'UNKNOWN').upper()}_CLOSED_5M_CANDLES",
        "path_model": "SAME_ENTRY_TARGET_FEES_24H_HORIZON",
        "max_bars": bars,
        "bars_observed": 0,
        "last_processed_open_time_ms": captured_at_ms // INTERVAL_MS * INTERVAL_MS,
        "highest_price_after_entry": entry,
        "lowest_price_after_entry": entry,
        "max_favorable_percent": 0.0,
        "max_adverse_percent": 0.0,
        "structural_comparison": classification,
        "atr_path": _path_snapshot(
            stop_price=atr_stop,
            entry_price=entry,
            max_bars=bars,
        ),
        "structural_path": _path_snapshot(
            stop_price=structural_stop,
            entry_price=entry,
            max_bars=bars,
        ),
        "status": "OBSERVING",
        "completed_at_utc": None,
        "measurement_caveat": (
            "Paired price-path counterfactual only. Both paths share the actual Paper entry, "
            "the same captured target, the same fee assumption, and the same closed 5m candles. "
            "No order fills, spread, slippage, queue position, or actual execution are simulated. "
            "The ATR path uses the entry-time 2x-ATR stop, not later Trade Manager stop changes."
        ),
        "trading_logic_changed": False,
    }



def build_structural_stop_comparison_decision(
    position: Any,
    *,
    source_capture_id: str,
    venue: str,
    venue_mode: str,
    reason: str,
) -> dict[str, Any]:
    """Persist a bounded reason when a real Paper position cannot be paired."""
    position_id = str(_value(position, "position_id", "") or "").strip()
    metadata = _value(position, "entry_metadata", {})
    metadata = metadata if isinstance(metadata, Mapping) else {}
    return {
        "schema_version": 1,
        "trial_name": TRIAL_NAME,
        "record_type": "DECISION",
        "record_id": f"{position_id}:DECISION",
        "capture_id": f"{position_id}:DECISION",
        "position_id": position_id,
        "source_capture_id": str(source_capture_id or ""),
        "symbol": str(_value(position, "symbol", "") or "").upper(),
        "venue": str(venue or "UNKNOWN").upper(),
        "venue_mode": str(venue_mode or "UNKNOWN").upper(),
        "trade_mode": str(metadata.get("trade_mode") or _value(position, "trade_mode", "UNKNOWN")).upper(),
        "mode": "PAPER_ONLY",
        "status": "UNMEASURABLE_CONTEXT",
        "reason": str(reason or "UNKNOWN"),
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "trading_logic_changed": False,
    }


def _finish_path(
    path: dict[str, Any],
    *,
    status: str,
    reason: str,
    exit_price: float | None = None,
    bars_observed: int,
    entry_price: float,
    fee_percent: float,
) -> None:
    path["status"] = status
    path["outcome_class"] = (
        "STOP" if status == "STOP_HIT"
        else "TARGET" if status == "TARGET_HIT"
        else "TIME_EXIT" if status == "TIME_LIMIT_EXIT"
        else "AMBIGUOUS" if status == "AMBIGUOUS_SAME_CANDLE"
        else "INCOMPLETE_DATA_GAP" if status == "DATA_GAP"
        else "UNMEASURABLE"
    )
    path["exit_reason"] = reason
    path["hypothetical_exit_price"] = exit_price
    path["bars_to_exit"] = int(bars_observed)
    if exit_price is None or exit_price <= 0:
        return
    gross = (exit_price - entry_price) / entry_price * 100.0
    net = gross - fee_percent
    risk_percent = _number(path.get("stop_distance_percent"))
    path["gross_return_percent"] = round(gross, 8)
    path["net_return_percent_after_estimated_fees"] = round(net, 8)
    path["net_r_multiple_after_estimated_fees"] = (
        round(net / risk_percent, 8)
        if risk_percent is not None and risk_percent > 0
        else None
    )


def _path_is_terminal(path: Mapping[str, Any]) -> bool:
    return str(path.get("status") or "").upper() in _TERMINAL


def advance_structural_stop_comparison(
    watch: Mapping[str, Any],
    candles: Iterable[Mapping[str, Any]],
) -> tuple[dict[str, Any], bool]:
    """Advance both stop alternatives over the same new closed 5m candles."""
    record = deepcopy(dict(watch))
    if str(record.get("status") or "").upper() != "OBSERVING":
        return record, False

    entry = _positive(record.get("entry_price"))
    captured_at_ms = _number(record.get("entry_capture_at_ms"))
    last_open = _number(record.get("last_processed_open_time_ms"))
    target = _positive(record.get("target_price"))
    if entry is None or captured_at_ms is None or last_open is None or target is None:
        record["status"] = "UNMEASURABLE_CONTEXT"
        record["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
        return record, True

    atr_path = record.get("atr_path")
    structural_path = record.get("structural_path")
    if not isinstance(atr_path, dict) or not isinstance(structural_path, dict):
        record["status"] = "UNMEASURABLE_CONTEXT"
        record["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
        return record, True

    fee_percent = _number(record.get("estimated_round_trip_fee_percent")) or 0.0
    bars_observed = int(record.get("bars_observed") or 0)
    max_bars = max(1, int(record.get("max_bars") or DEFAULT_MAX_BARS))
    highest = _positive(record.get("highest_price_after_entry")) or entry
    lowest = _positive(record.get("lowest_price_after_entry")) or entry
    changed = False

    ordered = sorted(
        (row for row in candles if isinstance(row, Mapping)),
        key=lambda row: int(_number(row.get("open_time")) or 0),
    )
    for candle in ordered:
        if candle.get("is_closed") is False:
            continue
        open_time = _number(candle.get("open_time"))
        high = _positive(candle.get("high"))
        low = _positive(candle.get("low"))
        close = _positive(candle.get("close"))
        if open_time is None or high is None or low is None or close is None:
            continue
        open_time = int(open_time)
        # The entire candle containing the entry is excluded. Its high/low
        # cannot establish whether the move happened before or after entry.
        if open_time <= captured_at_ms or open_time <= int(last_open):
            continue
        if high < low:
            continue
        if open_time - int(last_open) > INTERVAL_MS:
            for key, path in (("atr_path", atr_path), ("structural_path", structural_path)):
                if not _path_is_terminal(path):
                    _finish_path(
                        path,
                        status="DATA_GAP",
                        reason="MISSING_CLOSED_5M_CANDLE",
                        bars_observed=bars_observed,
                        entry_price=entry,
                        fee_percent=fee_percent,
                    )
            record["data_gap_at_open_time_ms"] = open_time
            changed = True
            break

        bars_observed += 1
        last_open = open_time
        highest = max(highest, high)
        lowest = min(lowest, low)
        changed = True
        record["bars_observed"] = bars_observed
        record["last_processed_open_time_ms"] = last_open
        record["highest_price_after_entry"] = highest
        record["lowest_price_after_entry"] = lowest
        record["max_favorable_percent"] = round(max(0.0, (highest - entry) / entry * 100.0), 8)
        record["max_adverse_percent"] = round(min(0.0, (lowest - entry) / entry * 100.0), 8)

        for path_name, path in (("ATR", atr_path), ("STRUCTURAL", structural_path)):
            if _path_is_terminal(path):
                continue
            stop = _positive(path.get("stop_price"))
            stop_hit = stop is not None and low <= stop
            target_hit = high >= target
            if stop_hit and target_hit:
                _finish_path(
                    path,
                    status="AMBIGUOUS_SAME_CANDLE",
                    reason="STOP_AND_SHARED_TARGET_TOUCHED_WITHIN_SAME_5M_CANDLE",
                    bars_observed=bars_observed,
                    entry_price=entry,
                    fee_percent=fee_percent,
                )
            elif stop_hit:
                _finish_path(
                    path,
                    status="STOP_HIT",
                    reason=f"{path_name}_STOP_TOUCHED",
                    exit_price=stop,
                    bars_observed=bars_observed,
                    entry_price=entry,
                    fee_percent=fee_percent,
                )
            elif target_hit:
                _finish_path(
                    path,
                    status="TARGET_HIT",
                    reason="SHARED_TARGET_TOUCHED",
                    exit_price=target,
                    bars_observed=bars_observed,
                    entry_price=entry,
                    fee_percent=fee_percent,
                )
            elif bars_observed >= max_bars:
                _finish_path(
                    path,
                    status="TIME_LIMIT_EXIT",
                    reason=f"MAX_{max_bars}_CLOSED_5M_BARS_REACHED",
                    exit_price=close,
                    bars_observed=bars_observed,
                    entry_price=entry,
                    fee_percent=fee_percent,
                )

        if _path_is_terminal(atr_path) and _path_is_terminal(structural_path):
            break

    record["bars_observed"] = bars_observed
    record["last_processed_open_time_ms"] = int(last_open)
    if _path_is_terminal(atr_path) and _path_is_terminal(structural_path):
        record["status"] = "COMPLETE"
        record["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
    else:
        record["status"] = "OBSERVING"
    return record, changed


def _path_metrics(rows: list[Mapping[str, Any]], path_key: str) -> dict[str, Any]:
    finals = [
        row for row in rows
        if isinstance(row.get(path_key), Mapping)
        and str(row[path_key].get("status") or "").upper() in _DECISIVE
    ]
    returns = [
        _number(row[path_key].get("net_return_percent_after_estimated_fees"))
        for row in finals
    ]
    values = [value for value in returns if value is not None]
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value < 0]
    positive = sum(wins)
    negative = abs(sum(losses))
    return {
        "decisive_positions": len(values),
        "wins": len(wins),
        "losses": len(losses),
        "flats": sum(1 for value in values if value == 0),
        "win_rate_percent": round(len(wins) / len(values) * 100.0, 4) if values else None,
        "average_net_return_percent": round(sum(values) / len(values), 8) if values else None,
        "sum_net_return_percent": round(sum(values), 8) if values else None,
        "profit_factor_after_estimated_fees": (
            round(positive / negative, 8)
            if negative > 0 else ("INF" if positive > 0 else None)
        ),
        "outcomes": dict(Counter(
            str(row[path_key].get("status") or "UNKNOWN").upper()
            for row in rows if isinstance(row.get(path_key), Mapping)
        )),
    }


def build_structural_stop_comparison_report(records: Any) -> dict[str, Any]:
    """Summarize unique Paper positions and paired stop-path outcomes."""
    source = [
        dict(row) for row in records
        if isinstance(row, Mapping)
        and row.get("trial_name") == TRIAL_NAME
        and row.get("position_id")
    ] if isinstance(records, (list, tuple)) else []

    starts: dict[str, dict[str, Any]] = {}
    finals: dict[str, dict[str, Any]] = {}
    decisions: dict[str, dict[str, Any]] = {}
    for row in source:
        position_id = str(row.get("position_id") or "")
        if row.get("record_type") == "START":
            starts[position_id] = row
        elif row.get("record_type") == "FINAL":
            finals[position_id] = row
        elif row.get("record_type") == "DECISION":
            decisions[position_id] = row

    rows = list(finals.values())
    paired: list[float] = []
    structural_better = structural_worse = equal = 0
    paired_statuses: Counter[str] = Counter()
    for row in rows:
        atr = row.get("atr_path") if isinstance(row.get("atr_path"), Mapping) else {}
        structural = row.get("structural_path") if isinstance(row.get("structural_path"), Mapping) else {}
        atr_status = str(atr.get("status") or "").upper()
        structural_status = str(structural.get("status") or "").upper()
        paired_statuses[f"ATR={atr_status}|STRUCTURAL={structural_status}"] += 1
        if atr_status not in _DECISIVE or structural_status not in _DECISIVE:
            continue
        atr_net = _number(atr.get("net_return_percent_after_estimated_fees"))
        structural_net = _number(structural.get("net_return_percent_after_estimated_fees"))
        if atr_net is None or structural_net is None:
            continue
        delta = structural_net - atr_net
        paired.append(delta)
        if delta > 1e-9:
            structural_better += 1
        elif delta < -1e-9:
            structural_worse += 1
        else:
            equal += 1

    by_venue_mode: dict[str, dict[str, Any]] = {}
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        group = "|".join((
            str(row.get("venue") or "UNKNOWN").upper(),
            str(row.get("venue_mode") or "UNKNOWN").upper(),
            str(row.get("trade_mode") or "UNKNOWN").upper(),
        ))
        grouped[group].append(row)
    for group, group_rows in grouped.items():
        by_venue_mode[group] = {
            "positions_completed": len(group_rows),
            "atr": _path_metrics(group_rows, "atr_path"),
            "structural": _path_metrics(group_rows, "structural_path"),
        }

    open_ids = set(starts) - set(finals)
    active = [
        starts[position_id] for position_id in sorted(open_ids)
        if str(starts[position_id].get("status") or "").upper() == "OBSERVING"
    ]

    return {
        "available": True,
        "mode": "PAPER_ONLY",
        "trial_name": TRIAL_NAME,
        "shadow_only": True,
        "coverage": {
            "unique_positions_started": len(starts),
            "positions_completed": len(finals),
            "positions_active": len(active),
            "positions_without_final_record": len(open_ids),
            "positions_skipped_unmeasurable": len(decisions),
            "skip_reasons": dict(Counter(str(row.get("reason") or "UNKNOWN") for row in decisions.values())),
        },
        "comparison": {
            "paired_decisive_positions": len(paired),
            "structural_better": structural_better,
            "structural_worse": structural_worse,
            "equal": equal,
            "average_structural_minus_atr_net_return_percent": (
                round(sum(paired) / len(paired), 8) if paired else None
            ),
            "paired_statuses": dict(paired_statuses),
        },
        "overall": {
            "atr": _path_metrics(rows, "atr_path"),
            "structural": _path_metrics(rows, "structural_path"),
        },
        "by_venue_mode_trade_mode": by_venue_mode,
        "active_positions": [
            {
                "position_id": row.get("position_id"),
                "symbol": row.get("symbol"),
                "venue": row.get("venue"),
                "venue_mode": row.get("venue_mode"),
                "trade_mode": row.get("trade_mode"),
                "bars_observed": row.get("bars_observed"),
                "max_bars": row.get("max_bars"),
                "structural_comparison": row.get("structural_comparison"),
                "atr_status": (row.get("atr_path") or {}).get("status"),
                "structural_status": (row.get("structural_path") or {}).get("status"),
            }
            for row in active[-100:]
        ],
        "interpretation": {
            "pairing": "Both paths use the same actual Paper entry, exact captured ATR and structural stop distances, one shared captured target, one fee assumption, and the same venue's closed 5m candles.",
            "decision_rule": "Only positions where both paths have decisive STOP_HIT, TARGET_HIT, or TIME_LIMIT_EXIT outcomes enter the paired comparison.",
            "ambiguity": "A stop and shared target touched in the same 5m candle is marked AMBIGUOUS_SAME_CANDLE and excluded from decisive comparisons.",
            "data_gaps": "Missing 5m candles are marked DATA_GAP and excluded; they are never counted as losses.",
            "fees": "Both paths deduct the same estimated round-trip entry and exit fee. Spread and slippage are not simulated.",
            "authority": "The Paper position continues using its existing ATR/Trade Manager/Exit authority. Neither hypothetical path changes the position or submits orders.",
            "trading_logic_changed": False,
        },
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }


__all__ = [
    "DEFAULT_MAX_BARS",
    "INTERVAL_MS",
    "TRIAL_NAME",
    "advance_structural_stop_comparison",
    "build_structural_stop_comparison_decision",
    "build_structural_stop_comparison_report",
    "build_structural_stop_comparison_watch",
]
