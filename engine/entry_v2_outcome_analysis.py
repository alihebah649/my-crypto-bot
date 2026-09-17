"""Post-hoc outcome analysis for Entry v2 shadow captures.

This module is descriptive only. It joins pre-execution Entry v2 captures to
actual Legacy-executed Paper positions by capture_id and reports realized
outcomes. It does not claim the hypothetical V2 decision caused an outcome.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable, Mapping


_ACTIVE_STATUSES = {"OPEN", "HOLD", "REVIEW_REQUIRED", "PARTIALLY_CLOSED"}


def _value(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _status_name(position: Any) -> str:
    status = _value(position, "status", "")
    return str(getattr(status, "name", status) or "").upper()


def _position_metadata(position: Any) -> Mapping[str, Any]:
    value = _value(position, "entry_metadata", {})
    return value if isinstance(value, Mapping) else {}


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _bucket() -> dict[str, Any]:
    return {
        "positions": 0,
        "closed_positions": 0,
        "open_positions": 0,
        "wins": 0,
        "losses": 0,
        "flat": 0,
        "realized_pnl": 0.0,
        "fees": 0.0,
    }


def _add_outcome(bucket: dict[str, Any], position: Any) -> None:
    bucket["positions"] += 1
    status = _status_name(position)
    realized = _float(_value(position, "realized_pnl", 0.0))
    fees = _float(_value(position, "total_fees", 0.0))
    bucket["realized_pnl"] += realized
    bucket["fees"] += fees
    if status == "CLOSED":
        bucket["closed_positions"] += 1
        if realized > 0:
            bucket["wins"] += 1
        elif realized < 0:
            bucket["losses"] += 1
        else:
            bucket["flat"] += 1
    elif status in _ACTIVE_STATUSES:
        bucket["open_positions"] += 1


def analyze_entry_v2_outcomes(
    captures: Iterable[Mapping[str, Any]],
    positions: Iterable[Any],
) -> dict[str, Any]:
    """Join captures to actual positions and summarize realized outcomes."""
    capture_list = list(captures)
    position_list = list(positions)
    capture_by_id = {
        str(record.get("capture_id")): record
        for record in capture_list
        if record.get("capture_id")
    }

    by_decision: dict[str, dict[str, Any]] = {
        "V2_APPROVED": _bucket(),
        "V2_REJECTED": _bucket(),
    }
    by_lane: dict[str, dict[str, Any]] = defaultdict(_bucket)
    by_gate: dict[str, dict[str, Any]] = defaultdict(_bucket)
    unmatched_positions: list[str] = []
    matched_position_ids: set[str] = set()
    matched_capture_ids: set[str] = set()
    rejected_execution_ids: list[str] = []

    for position in position_list:
        metadata = _position_metadata(position)
        capture_id = metadata.get("entry_v2_shadow_capture_id")
        position_id = str(_value(position, "position_id", ""))
        if not capture_id or str(capture_id) not in capture_by_id:
            if position_id:
                unmatched_positions.append(position_id)
            continue

        normalized_capture_id = str(capture_id)
        capture = capture_by_id[normalized_capture_id]
        decision = capture.get("v2_decision", {}) or {}
        approved = decision.get("approved") is True
        decision_key = "V2_APPROVED" if approved else "V2_REJECTED"
        lane = str(decision.get("trade_mode") or metadata.get("trade_mode") or "UNKNOWN").upper()
        gate = str(decision.get("failed_gate") or "NONE")

        _add_outcome(by_decision[decision_key], position)
        _add_outcome(by_lane[lane], position)
        _add_outcome(by_gate[gate], position)
        matched_capture_ids.add(normalized_capture_id)
        if position_id:
            matched_position_ids.add(position_id)
        if not approved and position_id:
            rejected_execution_ids.append(position_id)

    unmatched_captures = [
        str(record.get("capture_id"))
        for record in capture_list
        if record.get("capture_id") and str(record.get("capture_id")) not in matched_capture_ids
    ]

    return {
        "schema_version": 1,
        "capture_count": len(capture_list),
        "matched_position_count": len(matched_position_ids),
        "unmatched_position_count": len(unmatched_positions),
        "unmatched_position_ids": unmatched_positions,
        "unmatched_capture_count": len(unmatched_captures),
        "unmatched_capture_ids": unmatched_captures,
        "legacy_executed_v2_rejected": len(rejected_execution_ids),
        "legacy_executed_v2_rejected_position_ids": rejected_execution_ids,
        "by_decision": by_decision,
        "by_lane": dict(by_lane),
        "by_failed_gate": dict(by_gate),
    }


__all__ = ["analyze_entry_v2_outcomes"]
