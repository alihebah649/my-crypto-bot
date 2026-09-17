"""Pure descriptive report for accumulated Entry v2 shadow evidence.

This module reads already-captured observations and already-executed Paper
positions. It never changes execution authority, state, sizing, or Trade
Manager behavior. The report is deliberately descriptive and does not claim
that the hypothetical Entry v2 decision caused any observed P&L outcome.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from .entry_v2_outcome_analysis import analyze_entry_v2_outcomes


_ACTIVE_STATUSES = {"OPEN", "HOLD", "REVIEW_REQUIRED", "PARTIALLY_CLOSED"}


def _value(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _position_metadata(position: Any) -> Mapping[str, Any]:
    value = _value(position, "entry_metadata", {})
    return value if isinstance(value, Mapping) else {}


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _status_name(position: Any) -> str:
    status = _value(position, "status", "")
    return str(getattr(status, "name", status) or "").upper()


def _capture_identity(capture: Mapping[str, Any]) -> str:
    value = capture.get("capture_id")
    return str(value) if value else ""


def _decision(capture: Mapping[str, Any]) -> Mapping[str, Any]:
    value = capture.get("v2_decision", {})
    return value if isinstance(value, Mapping) else {}


def _risk(capture: Mapping[str, Any]) -> Mapping[str, Any]:
    scenario = capture.get("entry_scenario", {})
    if not isinstance(scenario, Mapping):
        return {}
    value = scenario.get("risk", {})
    return value if isinstance(value, Mapping) else {}


def _position_row(position: Any, capture: Mapping[str, Any]) -> dict[str, Any]:
    decision = _decision(capture)
    risk = _risk(capture)
    metadata = _position_metadata(position)
    return {
        "capture_id": _capture_identity(capture),
        "position_id": str(_value(position, "position_id", "")),
        "symbol": str(capture.get("symbol") or _value(position, "symbol", "")).upper(),
        "captured_at": str(capture.get("captured_at") or ""),
        "status": _status_name(position),
        "v2_approved": decision.get("approved"),
        "v2_decision": decision.get("decision"),
        "trade_mode": str(decision.get("trade_mode") or metadata.get("trade_mode") or "UNKNOWN").upper(),
        "setup_type": decision.get("setup_type"),
        "failed_gate": decision.get("failed_gate") or "NONE",
        "target_price": risk.get("target_price"),
        "target_status": risk.get("target_status"),
        "reward_risk": risk.get("reward_risk"),
        "realized_pnl": _float(_value(position, "realized_pnl", 0.0)),
        "fees": _float(_value(position, "total_fees", 0.0)),
    }


def build_entry_v2_shadow_report(
    captures: Iterable[Mapping[str, Any]],
    positions: Iterable[Any],
    *,
    max_rejected_execution_rows: int = 100,
) -> dict[str, Any]:
    """Build a compact empirical report from durable captures and Paper positions."""
    if max_rejected_execution_rows < 0:
        raise ValueError("max_rejected_execution_rows must be non-negative")

    capture_list = [record for record in captures if isinstance(record, Mapping)]
    position_list = list(positions)
    outcome = analyze_entry_v2_outcomes(capture_list, position_list)
    capture_by_id = {
        _capture_identity(record): record
        for record in capture_list
        if _capture_identity(record)
    }

    rejected_execution_rows: list[dict[str, Any]] = []

    for position in position_list:
        metadata = _position_metadata(position)
        capture_id = str(metadata.get("entry_v2_shadow_capture_id") or "")
        capture = capture_by_id.get(capture_id)
        if capture is None:
            continue
        row = _position_row(position, capture)
        if row["v2_approved"] is False:
            rejected_execution_rows.append(row)

    rejected_execution_rows.sort(key=lambda row: (row["captured_at"], row["capture_id"], row["position_id"]))

    closed_rejected = [row for row in rejected_execution_rows if row["status"] == "CLOSED"]
    rejected_realized_pnl = sum(row["realized_pnl"] for row in closed_rejected)
    rejected_fees = sum(row["fees"] for row in closed_rejected)
    rejected_losses = sum(1 for row in closed_rejected if row["realized_pnl"] < 0)
    rejected_wins = sum(1 for row in closed_rejected if row["realized_pnl"] > 0)
    rejected_open = sum(1 for row in rejected_execution_rows if row["status"] in _ACTIVE_STATUSES)

    return {
        "schema_version": 1,
        "coverage": {
            "captures": outcome["capture_count"],
            "matched_positions": outcome["matched_position_count"],
            "unmatched_positions": outcome["unmatched_position_count"],
            "unmatched_captures": outcome["unmatched_capture_count"],
        },
        "decision_flow": {
            "v2_approved": sum(1 for record in capture_list if _decision(record).get("approved") is True),
            "v2_rejected": sum(1 for record in capture_list if _decision(record).get("approved") is False),
            "legacy_executed_v2_rejected": outcome["legacy_executed_v2_rejected"],
        },
        "legacy_executed_v2_rejected_outcomes": {
            "positions": len(rejected_execution_rows),
            "closed_positions": len(closed_rejected),
            "open_positions": rejected_open,
            "wins": rejected_wins,
            "losses": rejected_losses,
            "realized_pnl": rejected_realized_pnl,
            "fees": rejected_fees,
        },
        "by_decision": outcome["by_decision"],
        "by_lane": outcome["by_lane"],
        "by_failed_gate": outcome["by_failed_gate"],
        "rejected_executions": rejected_execution_rows[:max_rejected_execution_rows],
        "unmatched_capture_ids": outcome["unmatched_capture_ids"],
        "unmatched_position_ids": outcome["unmatched_position_ids"],
    }


__all__ = ["build_entry_v2_shadow_report"]
