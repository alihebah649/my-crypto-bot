"""Diagnostic attribution for Paper entry decisions.

This module records how Legacy, Brain Authority, Entry v2, and downstream
opening relate to one another. It never changes trading decisions.
"""
from __future__ import annotations

from typing import Any, Mapping


SCHEMA_VERSION = 1
LANES = {"SCALP", "SWING"}


def _lane_signal(legacy_result: Mapping[str, Any], lane: str) -> str:
    lane = str(lane or "").upper()
    if lane == "SCALP":
        return str(
            legacy_result.get("scalp_signal", legacy_result.get("signal", "HOLD"))
            or "HOLD"
        ).upper()
    if lane == "SWING":
        return str(
            legacy_result.get("swing_signal", legacy_result.get("signal", "HOLD"))
            or "HOLD"
        ).upper()
    return str(legacy_result.get("signal", "HOLD") or "HOLD").upper()


def build_entry_decision_chain(
    legacy_result: Mapping[str, Any] | None,
    *,
    trade_mode: str,
    brain_record: Mapping[str, Any] | None = None,
    v2_record: Mapping[str, Any] | None = None,
    final_approved: bool | None = None,
    execution_attempted: bool = False,
    position_opened: bool = False,
    failed_gate: str | None = None,
) -> dict[str, Any]:
    legacy = legacy_result if isinstance(legacy_result, Mapping) else {}
    lane = str(trade_mode or "").upper()
    if lane not in LANES:
        lane = str(trade_mode or "NONE").upper()

    brain = brain_record if isinstance(brain_record, Mapping) else None
    v2 = v2_record if isinstance(v2_record, Mapping) else None

    brain_bypass_reason = (
        str(brain.get("reason") or "")
        if brain and str(brain.get("decision_state") or "").upper()
        == "BYPASS_INCOMPLETE_CONTEXT"
        else None
    )
    brain_evaluated = bool(brain) and brain_bypass_reason is None

    legacy_approved = _lane_signal(legacy, lane) == "BUY"
    v2_approved = None if v2 is None else bool(v2.get("v2_approved", v2.get("approved", False)))

    return {
        "schema_version": SCHEMA_VERSION,
        "trade_mode": lane,
        "legacy": {
            "approved": legacy_approved,
            "signal": _lane_signal(legacy, lane),
            "score": (
                legacy.get("scalp_score")
                if lane == "SCALP"
                else legacy.get("swing_score")
                if lane == "SWING"
                else legacy.get("score")
            ),
        },
        "brain_authority": {
            "evaluated": brain_evaluated,
            "bypassed": brain_bypass_reason is not None,
            "bypass_reason": brain_bypass_reason,
            "allowed": None if brain is None else bool(brain.get("allowed", False)),
            "action": brain.get("brain_action") if brain else None,
            "reason": brain.get("brain_reason") if brain else None,
            "confidence": brain.get("brain_confidence") if brain else None,
            "capture_id": brain.get("capture_id") if brain else None,
        },
        "entry_v2": {
            "available": v2 is not None,
            "approved": v2_approved,
            "decision": v2.get("v2_decision") if v2 else None,
            "failed_gate": v2.get("v2_failed_gate") if v2 else None,
            "capture_id": v2.get("capture_id") if v2 else None,
        },
        "final": {
            "approved": final_approved,
            "execution_attempted": bool(execution_attempted),
            "position_opened": bool(position_opened),
            "failed_gate": failed_gate,
        },
    }


__all__ = ["SCHEMA_VERSION", "build_entry_decision_chain"]
