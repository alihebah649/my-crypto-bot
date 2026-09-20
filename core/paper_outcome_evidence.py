"""Normalized Paper outcome evidence for post-trade analysis.

This module is diagnostic-only. It converts an already-closed Paper position
plus its captured Entry v2 / Brain observations into one JSON-safe record for
logging. It does not change execution, risk, strategy, or position lifecycle.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from engine.adaptive_scalp_shadow import derive_scalp_timing_profile


def _safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_safe(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _iso(ts: Any) -> str | None:
    try:
        value = float(ts)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()


def build_paper_outcome_evidence(
    position: Any,
    *,
    brain_record: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    entry_metadata = getattr(position, "entry_metadata", {}) or {}
    exit_metadata = getattr(position, "exit_metadata", {}) or {}
    entry_context = getattr(position, "entry_context", {}) or {}
    strategy = (
        entry_context.get("strategy_score", {})
        if isinstance(entry_context, Mapping)
        else {}
    ) or {}
    stop_distance_percent = 0.0
    try:
        entry_price = float(getattr(position, "entry_price", 0.0) or 0.0)
        stop_price = float(getattr(position, "stop_loss", 0.0) or 0.0)
        if entry_price > 0 and stop_price > 0:
            stop_distance_percent = max(0.0, (entry_price - stop_price) / entry_price * 100.0)
    except (TypeError, ValueError):
        stop_distance_percent = 0.0
    timing_profile = derive_scalp_timing_profile(strategy)
    v2 = entry_metadata.get("entry_v2_shadow_decision", {}) or {}

    opened_at = getattr(position, "opened_at", None)
    closed_at = getattr(position, "closed_at", None)
    holding_seconds = None
    try:
        if opened_at and closed_at:
            holding_seconds = max(0.0, float(closed_at) - float(opened_at))
    except (TypeError, ValueError):
        holding_seconds = None

    exit_price = exit_metadata.get(
        "exit_price",
        getattr(position, "current_price", 0.0),
    )

    record = {
        "schema_version": 1,
        "evidence_type": "PAPER_OUTCOME",
        "position_id": str(getattr(position, "position_id", "")),
        "symbol": str(getattr(position, "symbol", "")).upper(),
        "trade_mode": str(
            entry_metadata.get(
                "trade_mode",
                getattr(position, "trade_mode", "UNKNOWN"),
            )
        ).upper(),
        "opened_at": opened_at,
        "opened_at_utc": _iso(opened_at),
        "closed_at": closed_at,
        "closed_at_utc": _iso(closed_at),
        "holding_seconds": holding_seconds,
        "quantity": float(getattr(position, "quantity", 0.0) or 0.0),
        "entry_price": float(getattr(position, "entry_price", 0.0) or 0.0),
        "exit_price": float(exit_price or 0.0),
        "stop_loss": float(getattr(position, "stop_loss", 0.0) or 0.0),
        "take_profit": getattr(position, "take_profit", None),
        "gross_pnl": float(getattr(position, "gross_pnl", 0.0) or 0.0),
        "realized_pnl": float(getattr(position, "realized_pnl", 0.0) or 0.0),
        "fees": float(getattr(position, "total_fees", 0.0) or 0.0),
        "close_reason": getattr(
            getattr(position, "close_reason", None),
            "name",
            getattr(position, "close_reason", None),
        ),
        "entry_v2": {
            "capture_id": entry_metadata.get("entry_v2_shadow_capture_id"),
            "decision": v2.get("decision"),
            "approved": v2.get("approved"),
            "trade_mode": v2.get("trade_mode"),
            "setup_type": v2.get("setup_type"),
            "failed_gate": v2.get("failed_gate"),
            "reasons": list(v2.get("reasons", []) or []),
            "target_price": entry_metadata.get("entry_v2_shadow_target_price"),
            "target_status": entry_metadata.get("entry_v2_shadow_target_status"),
            "reward_risk": entry_metadata.get("entry_v2_shadow_reward_risk"),
        },
        "brain": {
            "capture_id": (
                brain_record.get("capture_id")
                if isinstance(brain_record, Mapping)
                else entry_metadata.get("entry_v2_shadow_capture_id")
            ),
            "action": brain_record.get("brain_action") if isinstance(brain_record, Mapping) else None,
            "confidence": brain_record.get("brain_confidence") if isinstance(brain_record, Mapping) else None,
            "reason": brain_record.get("brain_reason") if isinstance(brain_record, Mapping) else None,
            "agreement": brain_record.get("agreement") if isinstance(brain_record, Mapping) else None,
        },
        "strategy": {
            "score": strategy.get("score"),
            "scalp_score": strategy.get("scalp_score"),
            "swing_score": strategy.get("swing_score"),
            "signal": strategy.get("signal"),
            "scalp_signal": strategy.get("scalp_signal"),
            "swing_signal": strategy.get("swing_signal"),
            "scalp_gate": strategy.get("scalp_gate"),
            "scalp_gate_reasons": list(strategy.get("scalp_gate_reasons", []) or []),
            "scalp_confirmed_reversal": strategy.get("scalp_confirmed_reversal"),
            "scalp_recovery_confirmation": strategy.get("scalp_recovery_confirmation"),
            "scalp_high_confidence_recovery": strategy.get("scalp_high_confidence_recovery"),
            "pattern": strategy.get("pattern"),
            "pattern_confirmed": strategy.get("pattern_confirmed"),
            "rsi5m": strategy.get("rsi5m"),
            "volume_ratio_5m": strategy.get("volume_ratio_5m"),
        },
        "regime": {
            "market": strategy.get("market_regime"),
            "symbol": strategy.get("symbol_regime"),
            "mtf_bias": strategy.get("mtf_bias"),
            "mtf_net": strategy.get("mtf_net"),
            "mtf_higher_timeframes_bearish": strategy.get("mtf_higher_timeframes_bearish"),
            "mtf_higher_timeframes_bullish": strategy.get("mtf_higher_timeframes_bullish"),
            "seller_failure_confirmed": strategy.get("seller_failure_confirmed"),
        },
        "freshness_5m": _safe(strategy.get("entry_freshness_5m")),
        "entry_forensics": {
            "scalp_rsi_phase": timing_profile["rsi_phase"],
            "pattern_family": timing_profile["pattern_family"],
            "combined_signature": timing_profile["combined_signature"],
            "recovery_confirmation": strategy.get("scalp_recovery_confirmation"),
            "recovery_trigger_count": strategy.get("scalp_recovery_trigger_count"),
            "recovery_trigger_reasons": list(strategy.get("scalp_recovery_trigger_reasons", []) or []),
            "volume_ratio_5m": strategy.get("volume_ratio_5m"),
            "mtf_bias": strategy.get("mtf_bias"),
            "mtf_net": strategy.get("mtf_net"),
            "decision_candle_age_seconds": _safe((strategy.get("entry_freshness_5m") or {}).get("decision_candle_age_seconds")) if isinstance(strategy.get("entry_freshness_5m"), Mapping) else None,
            "stop_distance_percent": round(stop_distance_percent, 6),
        },
        "entry_context_available": bool(entry_context),
    }
    return _safe(record)


__all__ = ["build_paper_outcome_evidence"]
