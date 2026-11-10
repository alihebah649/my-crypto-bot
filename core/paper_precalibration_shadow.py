"""Append-only evidence helpers for Paper-only pre-calibration Scalp candidates.

The old score is evaluated through the same Brain and Paper entry-economics
checks before any two-hour price-path watch can begin. Nothing here creates or
submits a Paper position or alters the active strategy.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from datetime import datetime, timezone
from math import isfinite
from typing import Any


TRIAL_NAME = "PAPER_SCALP_PRECALIBRATION"
MAX_BARS = 24
INTERVAL_MS = 5 * 60 * 1000


def candidate_identity(symbol: str, candle_open_time_ms: Any) -> str | None:
    """One candidate identity per symbol, lane, and closed 5m signal candle."""
    try:
        open_time = int(float(candle_open_time_ms))
    except (TypeError, ValueError, OverflowError):
        return None
    if open_time <= 0:
        return None
    normalized = str(symbol or "").strip().upper()
    if not normalized:
        return None
    return f"{TRIAL_NAME}:{normalized}:SCALP:{open_time}"


def entry_risk_snapshot(capture: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return the captured Entry v2 risk fields before any preflight uses them."""
    source = capture if isinstance(capture, Mapping) else {}
    scenario = source.get("entry_scenario")
    scenario = scenario if isinstance(scenario, Mapping) else {}
    risk = scenario.get("risk")
    return dict(risk) if isinstance(risk, Mapping) else {}


def build_precalibration_decision_record(
    *,
    candidate_id: str,
    symbol: str,
    candle_open_time_ms: int,
    captured_at_utc: str,
    prior_score: float,
    current_score: float,
    entry_price: float,
    stop_price: float | None,
    target_price: float | None,
    target_status: str,
    reward_risk: float | None,
    fee_rate_per_side: float,
    brain_record: Mapping[str, Any],
    economics: Mapping[str, Any],
    entry_v2_capture_id: str | None,
    entry_v2_decision: str | None,
    entry_v2_failed_gate: str | None,
    existing_position: bool,
    market_regime: str,
    symbol_regime: str,
    preflight_rejection: str | None = None,
    preflight_details: Mapping[str, Any] | None = None,
    market_data_rejection: str | None = None,
    market_data_details: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a compact, immutable explanation for a pre-calibration candidate."""
    brain = dict(brain_record or {})
    economics = dict(economics or {})
    context = brain.get("context") if isinstance(brain.get("context"), Mapping) else {}
    selective_veto = context.get("selective_v2_veto")
    brain_allowed = bool(brain.get("allowed"))

    preflight = str(preflight_rejection or "").strip().upper()
    market_rejection = str(market_data_rejection or "").strip().upper()
    if preflight:
        disposition = preflight
    elif existing_position:
        disposition = "SKIPPED_EXISTING_POSITION"
    elif not brain_allowed:
        disposition = "BRAIN_SELECTIVE_VETO" if selective_veto else "BRAIN_REJECTED"
    elif str(target_status or "").upper() != "VALID" or target_price is None:
        disposition = "NO_VALID_TARGET"
    elif not bool(economics.get("approved")):
        disposition = "ENTRY_ECONOMICS_REJECTED"
    elif market_rejection:
        disposition = market_rejection
    else:
        disposition = "BRAIN_ECONOMICS_QUALIFIED_WATCH"

    return {
        "schema_version": 1,
        "trial_name": TRIAL_NAME,
        "record_type": "DECISION",
        "record_id": f"{candidate_id}:DECISION",
        "candidate_id": candidate_id,
        "symbol": str(symbol or "").upper(),
        "trade_mode": "SCALP",
        "signal_candle_open_time_ms": int(candle_open_time_ms),
        "entry_capture_at_utc": str(captured_at_utc),
        "prior_formula_score": float(prior_score),
        "current_formula_score": float(current_score),
        "score_delta": round(float(prior_score) - float(current_score), 6),
        "entry_price": float(entry_price),
        "stop_price": float(stop_price) if stop_price is not None else None,
        "target_price": float(target_price) if target_price is not None else None,
        "target_status": str(target_status or "UNKNOWN").upper(),
        "expected_reward_risk": float(reward_risk) if reward_risk is not None else None,
        "fee_rate_per_side": float(fee_rate_per_side),
        "estimated_round_trip_fee_percent": round(float(fee_rate_per_side) * 200.0, 6),
        "brain_allowed": brain_allowed,
        "brain_reason": str(brain.get("brain_reason") or ""),
        "brain_action": str(brain.get("brain_action") or ""),
        "selective_v2_veto": str(selective_veto or ""),
        "preflight_rejection": preflight,
        "preflight_details": dict(preflight_details or {}),
        "market_data_rejection": market_rejection,
        "market_data_details": dict(market_data_details or {}),
        "existing_position": bool(existing_position),
        "market_regime": str(market_regime or "UNKNOWN").upper(),
        "symbol_regime": str(symbol_regime or "UNKNOWN").upper(),
        "entry_v2_capture_id": str(entry_v2_capture_id or ""),
        "entry_v2_decision": str(entry_v2_decision or ""),
        "entry_v2_failed_gate": str(entry_v2_failed_gate or ""),
        "economics": economics,
        "disposition": disposition,
        "risk_authority": "NOT_SIMULATED",
        "trade_manager_authority": "NOT_SIMULATED",
        "execution_authority": "NOT_SIMULATED",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "PAPER_ONLY",
        "trading_logic_changed": False,
    }


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if isfinite(number) else None


def build_precalibration_shadow_report(records: Any) -> dict[str, Any]:
    """Aggregate eligibility and 24-bar outcomes without counting scan repeats."""
    source = [dict(row) for row in records if isinstance(row, Mapping)] if isinstance(records, (list, tuple)) else []
    decisions = [row for row in source if row.get("record_type") == "DECISION"]
    starts = [row for row in source if row.get("record_type") == "START"]
    finals = [row for row in source if row.get("record_type") == "FINAL"]

    decision_by_id = {
        str(row.get("candidate_id") or ""): row
        for row in decisions
        if row.get("candidate_id")
    }
    start_by_id = {
        str(row.get("candidate_id") or row.get("source_capture_id") or ""): row
        for row in starts
        if row.get("candidate_id") or row.get("source_capture_id")
    }
    final_by_id = {
        str(row.get("candidate_id") or row.get("source_capture_id") or ""): row
        for row in finals
        if row.get("candidate_id") or row.get("source_capture_id")
    }

    unique_ids = set(decision_by_id) | set(start_by_id) | set(final_by_id)
    disposition_counts = Counter(
        str(row.get("disposition") or "UNKNOWN").upper()
        for row in decision_by_id.values()
    )
    disposition_counts.update(
        str(row.get("disposition") or "BRAIN_ECONOMICS_QUALIFIED_WATCH").upper()
        for row in start_by_id.values()
    )
    outcome_counts = Counter(
        str(row.get("status") or row.get("outcome_class") or "UNKNOWN").upper()
        for row in final_by_id.values()
    )
    decisive: list[tuple[dict[str, Any], float]] = []
    for row in final_by_id.values():
        status = str(row.get("status") or "").upper()
        net = _finite(row.get("net_return_percent_after_estimated_fees"))
        if status in {"TARGET_HIT", "STOP_HIT", "TIME_LIMIT_EXIT"} and net is not None:
            decisive.append((row, net))

    wins = sum(1 for _, net in decisive if net > 0)
    losses = sum(1 for _, net in decisive if net < 0)
    flats = sum(1 for _, net in decisive if net == 0)
    positive = sum(net for _, net in decisive if net > 0)
    negative = abs(sum(net for _, net in decisive if net < 0))
    net_values = [net for _, net in decisive]
    net_r_values = [
        value
        for row, _ in decisive
        if (value := _finite(row.get("net_r_multiple_after_estimated_fees"))) is not None
    ]

    active_ids = set(start_by_id) - set(final_by_id)
    recent = sorted(
        source,
        key=lambda row: str(
            row.get("completed_at_utc")
            or row.get("recorded_at_utc")
            or row.get("entry_capture_at_utc")
            or ""
        ),
        reverse=True,
    )[:30]

    return {
        "available": True,
        "mode": "PAPER_ONLY",
        "trial_name": TRIAL_NAME,
        "unique_candidate_count": len(unique_ids),
        "decision_records": len(decisions),
        "watch_started": len(start_by_id),
        "watch_active": len(active_ids),
        "watch_completed": len(final_by_id),
        "dispositions": dict(sorted(disposition_counts.items())),
        "outcomes": dict(sorted(outcome_counts.items())),
        "decisive_outcomes": len(decisive),
        "wins": wins,
        "losses": losses,
        "flats": flats,
        "win_rate_percent": round(wins / len(decisive) * 100.0, 4) if decisive else None,
        "net_profit_factor_after_estimated_fees": round(positive / negative, 6) if negative > 0 else (None if positive <= 0 else "INF"),
        "average_net_return_percent_after_estimated_fees": round(sum(net_values) / len(net_values), 6) if net_values else None,
        "sum_net_return_percent_after_estimated_fees": round(sum(net_values), 6) if net_values else None,
        "average_net_r_after_estimated_fees": round(sum(net_r_values) / len(net_r_values), 6) if net_r_values else None,
        "recent": recent,
        "interpretation": {
            "eligibility": "Only prior-formula-only candidates that pass the real preflight guards, current Brain (including Entry v2 selective veto), valid-target, and Paper entry-economics checks are monitored.",
            "path": "Entry v2 ATR stop and pivot target over at most 24 newly closed Binance 5m candles.",
            "unmodeled_authorities": "Risk Manager, Trade Manager, and Execution are not simulated; a measured price-path watch is not proof that a real Paper position would have been accepted or filled.",
            "fees": "Uses the MAIN Paper execution adapter fee rate on both entry and exit.",
            "excluded": "AMBIGUOUS_SAME_CANDLE, DATA_GAP, and UNMEASURABLE_CONTEXT are not included in decisive win/loss statistics.",
            "caveat": "Counterfactual price-path only; no simulated order fill, spread, slippage, queue position, or actual execution. This does not create a Paper position.",
            "trading_logic_changed": False,
        },
    }


__all__ = [
    "INTERVAL_MS",
    "MAX_BARS",
    "TRIAL_NAME",
    "build_precalibration_decision_record",
    "build_precalibration_shadow_report",
    "candidate_identity",
]
