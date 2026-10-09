"""Pure descriptive report for accumulated Entry v2 shadow evidence.

This module reads already-captured observations and already-executed Paper
positions. It never changes execution authority, state, sizing, or Trade
Manager behavior. The report is deliberately descriptive and does not claim
that the hypothetical Entry v2 decision caused any observed P&L outcome.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from .entry_v2_outcome_analysis import analyze_entry_v2_outcomes
from core.brain_shadow_outcome_analysis import analyze_brain_shadow_outcomes
from .adaptive_scalp_shadow import classify_adaptive_scalp


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


def _adaptive_scalp(capture: Mapping[str, Any]) -> Mapping[str, Any]:
    value = capture.get("adaptive_scalp_shadow")
    if isinstance(value, Mapping):
        return value
    return classify_adaptive_scalp(
        capture.get("legacy_result", {}) or {},
        capture.get("entry_scenario", {}) or {},
    )


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
        "adaptive_scalp_shadow": dict(_adaptive_scalp(capture)),
    }



def _positive_price(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _has_structural_capture(capture: Mapping[str, Any] | None) -> bool:
    if not isinstance(capture, Mapping):
        return False
    risk = _risk(capture)
    return any(
        key in risk
        for key in (
            "structural_stop_candidate",
            "atr_stop_loss",
            "structural_stop_would_widen_current_model",
        )
    )


def _structural_stop_observation(
    capture: Mapping[str, Any] | None,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Classify stop evidence from prices; never trust a stale false flag alone."""
    risk = _risk(capture) if isinstance(capture, Mapping) else {}
    metadata = metadata or {}
    candidate_raw = risk.get("structural_stop_candidate")
    if candidate_raw is None:
        candidate_raw = metadata.get("entry_v2_shadow_structural_stop_candidate")
    atr_raw = risk.get("atr_stop_loss")
    if atr_raw is None:
        atr_raw = metadata.get("entry_v2_shadow_atr_stop_loss")

    candidate = _positive_price(candidate_raw)
    atr_stop = _positive_price(atr_raw)
    candidate_presence = "PRESENT" if candidate is not None else "MISSING"
    if candidate is None or atr_stop is None:
        comparison = "UNKNOWN"
    else:
        # The structural candidate widens the current 2x-ATR stop only when
        # its price is lower than the ATR stop. This also corrects old records
        # whose false flag was emitted despite a missing candidate/ATR stop.
        comparison = "WOULD_WIDEN" if candidate < atr_stop else "WOULD_NOT_WIDEN"

    return {
        "candidate_presence": candidate_presence,
        "comparison": comparison,
        "candidate": candidate,
        "atr_stop_loss": atr_stop,
    }


def _has_recovery_capture(capture: Mapping[str, Any] | None) -> bool:
    if not isinstance(capture, Mapping):
        return False
    scenario = capture.get("entry_scenario", {})
    trigger = scenario.get("trigger", {}) if isinstance(scenario, Mapping) else {}
    return isinstance(trigger, Mapping) and "recovery_follow_through_shadow" in trigger


def _recovery_observation(
    capture: Mapping[str, Any] | None,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    value: Any = None
    if isinstance(capture, Mapping):
        scenario = capture.get("entry_scenario", {})
        trigger = scenario.get("trigger", {}) if isinstance(scenario, Mapping) else {}
        if isinstance(trigger, Mapping):
            value = trigger.get("recovery_follow_through_shadow")
    if value is None and isinstance(metadata, Mapping):
        value = metadata.get("entry_v2_shadow_recovery_follow_through_shadow")
    if not isinstance(value, Mapping):
        return {
            "would_be_action": "UNAVAILABLE",
            "applicable": None,
            "available": False,
        }
    return {
        **dict(value),
        "would_be_action": str(value.get("would_be_action") or "UNAVAILABLE").upper(),
    }


def _outcome_row(position: Any, observation: Mapping[str, Any]) -> dict[str, Any]:
    return {
        **dict(observation),
        "position_id": str(_value(position, "position_id", "")),
        "status": _status_name(position),
        "realized_pnl": _float(_value(position, "realized_pnl", 0.0)),
        "fees": _float(_value(position, "total_fees", 0.0)),
    }


def _empty_pnl_bucket() -> dict[str, Any]:
    return {
        "positions": 0,
        "wins": 0,
        "losses": 0,
        "flat": 0,
        "realized_pnl": 0.0,
        "fees": 0.0,
    }


def _closed_outcomes_by(
    rows: Iterable[Mapping[str, Any]],
    dimension: str,
) -> dict[str, dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        if str(row.get("status") or "").upper() != "CLOSED":
            continue
        key = str(row.get(dimension) or "UNKNOWN").upper()
        bucket = grouped.setdefault(key, _empty_pnl_bucket())
        pnl = _float(row.get("realized_pnl"))
        bucket["positions"] += 1
        bucket["realized_pnl"] += pnl
        bucket["fees"] += _float(row.get("fees"))
        if pnl > 0:
            bucket["wins"] += 1
        elif pnl < 0:
            bucket["losses"] += 1
        else:
            bucket["flat"] += 1
    return grouped


def build_entry_v2_shadow_report(
    captures: Iterable[Mapping[str, Any]],
    positions: Iterable[Any],
    *,
    brain_records: Iterable[Mapping[str, Any]] | None = None,
    max_rejected_execution_rows: int = 100,
) -> dict[str, Any]:
    """Build a compact empirical report from durable captures and Paper positions."""
    if max_rejected_execution_rows < 0:
        raise ValueError("max_rejected_execution_rows must be non-negative")

    capture_list = [record for record in captures if isinstance(record, Mapping)]
    position_list = list(positions)
    brain_record_list = [
        record for record in (brain_records or []) if isinstance(record, Mapping)
    ]
    outcome = analyze_entry_v2_outcomes(capture_list, position_list)
    capture_by_id = {
        _capture_identity(record): record
        for record in capture_list
        if _capture_identity(record)
    }

    rejected_execution_rows: list[dict[str, Any]] = []
    approved_execution_rows: list[dict[str, Any]] = []
    adaptive_rows: list[dict[str, Any]] = []
    structural_position_rows: list[dict[str, Any]] = []
    recovery_position_rows: list[dict[str, Any]] = []

    structural_metadata_keys = {
        "entry_v2_shadow_structural_stop_candidate",
        "entry_v2_shadow_atr_stop_loss",
        "entry_v2_shadow_structural_stop_would_widen_current_model",
    }
    recovery_metadata_key = "entry_v2_shadow_recovery_follow_through_shadow"

    for position in position_list:
        metadata = _position_metadata(position)
        capture_id = str(metadata.get("entry_v2_shadow_capture_id") or "")
        capture = capture_by_id.get(capture_id)

        # Build experiment telemetry independently of the Entry v2 P&L join.
        # The position's captured metadata remains usable when its capture row
        # is missing from the durable capture store.
        if _has_structural_capture(capture) or (
            capture is None and any(key in metadata for key in structural_metadata_keys)
        ):
            structural_position_rows.append(
                _outcome_row(position, _structural_stop_observation(capture, metadata))
            )
        if _has_recovery_capture(capture) or (
            capture is None and recovery_metadata_key in metadata
        ):
            recovery_position_rows.append(
                _outcome_row(position, _recovery_observation(capture, metadata))
            )

        if capture is None:
            continue
        row = _position_row(position, capture)
        if row["v2_approved"] is False:
            rejected_execution_rows.append(row)
        elif row["v2_approved"] is True:
            approved_execution_rows.append(row)
        if str(row["trade_mode"]).upper() == "SCALP":
            adaptive_rows.append(row)

    rejected_execution_rows.sort(key=lambda row: (row["captured_at"], row["capture_id"], row["position_id"]))
    approved_execution_rows.sort(key=lambda row: (row["captured_at"], row["capture_id"], row["position_id"]))
    adaptive_rows.sort(key=lambda row: (row["captured_at"], row["capture_id"], row["position_id"]))

    closed_rejected = [row for row in rejected_execution_rows if row["status"] == "CLOSED"]
    closed_adaptive = [row for row in adaptive_rows if row["status"] == "CLOSED"]
    rejected_realized_pnl = sum(row["realized_pnl"] for row in closed_rejected)
    rejected_fees = sum(row["fees"] for row in closed_rejected)
    rejected_losses = sum(1 for row in closed_rejected if row["realized_pnl"] < 0)
    rejected_wins = sum(1 for row in closed_rejected if row["realized_pnl"] > 0)
    rejected_open = sum(1 for row in rejected_execution_rows if row["status"] in _ACTIVE_STATUSES)

    structural_capture_rows = [
        _structural_stop_observation(record)
        for record in capture_list
        if _has_structural_capture(record)
    ]
    structural_candidate_presence = {
        "PRESENT": sum(1 for row in structural_capture_rows if row["candidate_presence"] == "PRESENT"),
        "MISSING": sum(1 for row in structural_capture_rows if row["candidate_presence"] == "MISSING"),
    }
    structural_comparison_counts = {
        action: sum(1 for row in structural_capture_rows if row["comparison"] == action)
        for action in ("WOULD_WIDEN", "WOULD_NOT_WIDEN", "UNKNOWN")
    }

    recovery_capture_rows = [
        _recovery_observation(record)
        for record in capture_list
    ]
    recovery_action_counts: dict[str, int] = {}
    for row in recovery_capture_rows:
        action = str(row.get("would_be_action") or "UNAVAILABLE").upper()
        recovery_action_counts[action] = recovery_action_counts.get(action, 0) + 1

    by_adaptive_class: dict[str, dict[str, Any]] = {}
    by_maturity_experiment: dict[str, dict[str, Any]] = {}
    for row in closed_adaptive:
        classification = str((row["adaptive_scalp_shadow"] or {}).get("classification") or "UNAVAILABLE")
        bucket = by_adaptive_class.setdefault(classification, {
            "positions": 0,
            "wins": 0,
            "losses": 0,
            "flat": 0,
            "realized_pnl": 0.0,
            "fees": 0.0,
        })
        bucket["positions"] += 1
        bucket["realized_pnl"] += row["realized_pnl"]
        bucket["fees"] += row["fees"]
        if row["realized_pnl"] > 0:
            bucket["wins"] += 1
        elif row["realized_pnl"] < 0:
            bucket["losses"] += 1
        else:
            bucket["flat"] += 1

    for row in closed_adaptive:
        adaptive = row["adaptive_scalp_shadow"] or {}
        experiment = adaptive.get("maturity_experiment") or {}
        action = str(experiment.get("would_be_action") or "UNAVAILABLE")
        bucket = by_maturity_experiment.setdefault(action, {
            "positions": 0,
            "wins": 0,
            "losses": 0,
            "flat": 0,
            "realized_pnl": 0.0,
            "fees": 0.0,
        })
        bucket["positions"] += 1
        bucket["realized_pnl"] += row["realized_pnl"]
        bucket["fees"] += row["fees"]
        if row["realized_pnl"] > 0:
            bucket["wins"] += 1
        elif row["realized_pnl"] < 0:
            bucket["losses"] += 1
        else:
            bucket["flat"] += 1

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
        "v2_approved_executions": approved_execution_rows[:max_rejected_execution_rows],
        "adaptive_scalp_shadow": {
            "closed_positions": len(closed_adaptive),
            "by_classification": by_adaptive_class,
            "maturity_experiment": {
                "rule_version": 1,
                "shadow_only": True,
                "by_action": by_maturity_experiment,
            },
        },
        "structural_stop_shadow": {
            "shadow_only": True,
            "capture_coverage": {
                "captures": len(capture_list),
                "observed_captures": len(structural_capture_rows),
                "candidate_presence": structural_candidate_presence,
                "comparison": structural_comparison_counts,
            },
            "closed_paper_outcomes": {
                "by_comparison": _closed_outcomes_by(structural_position_rows, "comparison"),
                "by_candidate_presence": _closed_outcomes_by(structural_position_rows, "candidate_presence"),
            },
            "interpretation": (
                "Comparison is derived from the captured structural-candidate and ATR-stop prices. "
                "UNKNOWN includes missing candidates or missing ATR stops; a legacy false flag "
                "does not turn missing evidence into WOULD_NOT_WIDEN."
            ),
        },
        "recovery_follow_through_shadow": {
            "rule_version": 1,
            "shadow_only": True,
            "capture_coverage": {
                "captures": len(capture_list),
                "observed_captures": sum(1 for record in capture_list if _has_recovery_capture(record)),
                "by_action": recovery_action_counts,
            },
            "closed_paper_outcomes": {
                "by_action": _closed_outcomes_by(recovery_position_rows, "would_be_action"),
                "interpretation": (
                    "WOULD_ALLOW/WOULD_BLOCK are counterfactual labels only. Every listed Paper "
                    "position was executed by the existing authority; P&L for WOULD_BLOCK positions "
                    "is not P&L that a block would necessarily have avoided."
                ),
            },
        },
        "brain_shadow": analyze_brain_shadow_outcomes(
            brain_record_list,
            position_list,
        ) if brain_record_list else None,
        "rejected_executions": rejected_execution_rows[:max_rejected_execution_rows],
        "unmatched_capture_ids": outcome["unmatched_capture_ids"],
        "unmatched_position_ids": outcome["unmatched_position_ids"],
    }


def build_entry_v2_shadow_report_endpoint_payload(
    analysis: Mapping[str, Any],
    *,
    venue_mode: str,
) -> dict[str, Any]:
    """Return aggregate-only, JSON-safe shadow evidence for the Paper diagnostics route."""
    report = analysis.get("shadow_report") if isinstance(analysis, Mapping) else None
    mode = str(venue_mode or "UNKNOWN").upper()
    if not isinstance(report, Mapping) or report.get("error"):
        return {
            "available": False,
            "mode": "PAPER",
            "venue_mode": mode,
            "shadow_only": True,
            "reason": "HISTORICAL_EVIDENCE_UNAVAILABLE",
        }

    return {
        "available": True,
        "mode": "PAPER",
        "venue_mode": mode,
        "shadow_only": True,
        "scope": {
            "capture_coverage": (
                "The report uses the configured durable Entry v2 capture store."
            ),
            "paper_outcomes": (
                "Closed-position outcomes come from this running service's Paper repository."
            ),
            "execution_impact": "NONE_DIAGNOSTICS_ONLY",
        },
        "coverage": report.get("coverage", {}),
        "structural_stop_shadow": report.get("structural_stop_shadow", {}),
        "recovery_follow_through_shadow": report.get(
            "recovery_follow_through_shadow", {}
        ),
    }


__all__ = ["build_entry_v2_shadow_report", "build_entry_v2_shadow_report_endpoint_payload"]
