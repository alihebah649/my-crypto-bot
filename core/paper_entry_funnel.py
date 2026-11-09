"""Durable, read-only attribution for Paper entry funnel decisions.

The funnel stores compact final-disposition records in a separate evidence type
within the existing paper_evidence table, linked by the same capture_id. Brain
Authority records remain immutable and the funnel never changes a decision.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import floor
from typing import Any, Mapping


FUNNEL_VERSION = 1
ENTRY_STAGES = {"ENTRY_GATE", "ENTRY_PIPELINE"}


def _safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_safe(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def build_entry_funnel_record(
    brain_record: Mapping[str, Any] | None,
    *,
    symbol: str,
    trade_mode: str,
    capture_id: str,
    captured_at: str | None,
    strategy_action: str,
    strategy_score: float | None,
    final_status: str,
    failed_gate: str | None,
    execution_attempted: bool,
    position_opened: bool,
    details: Mapping[str, Any] | None = None,
    recorded_at_utc: str | None = None,
) -> dict[str, Any] | None:
    """Attach one final disposition to a Brain record, or create a pre-Brain row."""
    identity = str(capture_id or "").strip()
    if not identity:
        return None

    source = dict(brain_record) if isinstance(brain_record, Mapping) else {}
    has_brain_decision = str(source.get("stage") or "").upper() == "ENTRY_GATE"
    # Copy only the small fields required by the funnel. The original Brain
    # evidence remains the authoritative, immutable source for full context.
    record = {
        key: source[key]
        for key in (
            "authority_version",
            "symbol",
            "trade_mode",
            "stage",
            "strategy_action",
            "strategy_score",
            "brain_action",
            "brain_confidence",
            "brain_reason",
            "allowed",
            "market_regime",
        )
        if key in source
    }
    record.setdefault("authority_version", "v1_guarded")
    record["capture_id"] = identity
    record["symbol"] = str(symbol or record.get("symbol") or "").upper()
    record["trade_mode"] = str(trade_mode or record.get("trade_mode") or "UNKNOWN").upper()
    record["stage"] = "ENTRY_GATE" if has_brain_decision else "ENTRY_PIPELINE"
    record.setdefault("strategy_action", str(strategy_action or "UNKNOWN").upper())
    if record.get("strategy_score") is None and strategy_score is not None:
        record["strategy_score"] = float(strategy_score)
    if not has_brain_decision:
        record.setdefault("brain_action", "NOT_EVALUATED")
        record.setdefault("brain_confidence", 0.0)
        record.setdefault("brain_reason", "PRE_BRAIN_REJECTION")
        record.setdefault("allowed", None)

    source_context = source.get("context")
    source_v2 = source_context.get("entry_v2_shadow", {}) if isinstance(source_context, Mapping) else {}
    timestamp = str(
        captured_at
        or source.get("captured_at")
        or (source_v2.get("captured_at") if isinstance(source_v2, Mapping) else "")
        or ""
    ).strip()
    if timestamp:
        record["captured_at"] = timestamp

    record["funnel_version"] = FUNNEL_VERSION
    record["final_decision"] = {
        "status": str(final_status or "UNKNOWN").upper(),
        "failed_gate": str(failed_gate or "").upper() or None,
        "execution_attempted": bool(execution_attempted),
        "position_opened": bool(position_opened),
        "recorded_at_utc": str(recorded_at_utc or datetime.now(timezone.utc).isoformat()),
        "details": _safe(dict(details or {})),
    }
    return record


def _parse_utc(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _record_timestamp(record: Mapping[str, Any]) -> datetime | None:
    value = record.get("captured_at")
    context = record.get("context")
    if not value and isinstance(context, Mapping):
        v2 = context.get("entry_v2_shadow")
        if isinstance(v2, Mapping):
            value = v2.get("captured_at")
    final = record.get("final_decision")
    if not value and isinstance(final, Mapping):
        value = final.get("recorded_at_utc")
    return _parse_utc(value)


def _increment(bucket: dict[str, int], key: str) -> None:
    bucket[key] = bucket.get(key, 0) + 1


def build_entry_funnel_report(records: Any) -> dict[str, Any]:
    """Summarize persisted entry decisions without treating scan repeats as trades."""
    source = records if isinstance(records, (list, tuple)) else []
    by_identity: dict[str, dict[str, Any]] = {}
    for raw in source:
        if not isinstance(raw, Mapping):
            continue
        if str(raw.get("stage") or "").upper() not in ENTRY_STAGES:
            continue
        identity = str(raw.get("capture_id") or "").strip()
        if identity:
            by_identity[identity] = dict(raw)

    eligible = list(by_identity.values())
    by_mode: dict[str, dict[str, Any]] = {}
    daily: dict[str, dict[str, Any]] = {}
    final_status_counts: dict[str, int] = {}
    failed_gate_counts: dict[str, int] = {}
    window_keys: set[tuple[str, str, int]] = set()

    for record in eligible:
        mode = str(record.get("trade_mode") or "UNKNOWN").upper()
        stage = str(record.get("stage") or "").upper()
        allowed = record.get("allowed")
        final = record.get("final_decision")
        final = final if isinstance(final, Mapping) else {}
        final_status = str(final.get("status") or "").upper()
        brain_reason = str(record.get("brain_reason") or "").upper()
        failed_gate = str(final.get("failed_gate") or "").upper()
        if not failed_gate and stage == "ENTRY_GATE" and allowed is False:
            failed_gate = brain_reason or "BRAIN_AUTHORITY"
        if not failed_gate and stage == "ENTRY_PIPELINE":
            failed_gate = "PRE_BRAIN_REJECTION"
        timestamp = _record_timestamp(record)
        day = timestamp.date().isoformat() if timestamp else "UNKNOWN_DATE"

        stats = by_mode.setdefault(mode, {
            "capture_records": 0,
            "brain_allowed": 0,
            "brain_blocked": 0,
            "pre_brain_blocked": 0,
            "final_decisions_recorded": 0,
            "blocked_after_brain": 0,
            "position_committed": 0,
            "final_outcome_unknown": 0,
        })
        stats["capture_records"] += 1
        if stage == "ENTRY_GATE":
            if allowed is True:
                stats["brain_allowed"] += 1
            elif allowed is False:
                stats["brain_blocked"] += 1
        elif stage == "ENTRY_PIPELINE":
            stats["pre_brain_blocked"] += 1

        if final_status:
            stats["final_decisions_recorded"] += 1
            _increment(final_status_counts, final_status)
            if failed_gate and final_status != "POSITION_COMMITTED":
                _increment(failed_gate_counts, failed_gate)
            if final_status == "POSITION_COMMITTED" or bool(final.get("position_opened")):
                stats["position_committed"] += 1
            elif stage == "ENTRY_GATE" and allowed is True:
                stats["blocked_after_brain"] += 1
        else:
            stats["final_outcome_unknown"] += 1
            if stage == "ENTRY_GATE" and allowed is False and brain_reason:
                _increment(failed_gate_counts, brain_reason)

        daily_row = daily.setdefault(day, {
            "capture_records": 0,
            "by_mode": {},
            "approximate_symbol_mode_5m_windows": 0,
        })
        daily_row["capture_records"] += 1
        mode_daily = daily_row["by_mode"].setdefault(mode, {
            "capture_records": 0,
            "brain_allowed": 0,
            "brain_blocked": 0,
            "pre_brain_blocked": 0,
            "final_decisions_recorded": 0,
            "blocked_after_brain": 0,
            "position_committed": 0,
            "final_outcome_unknown": 0,
        })
        mode_daily["capture_records"] += 1
        if stage == "ENTRY_GATE" and allowed is True:
            mode_daily["brain_allowed"] += 1
        elif stage == "ENTRY_GATE" and allowed is False:
            mode_daily["brain_blocked"] += 1
        elif stage == "ENTRY_PIPELINE":
            mode_daily["pre_brain_blocked"] += 1
        if final_status:
            mode_daily["final_decisions_recorded"] += 1
            if final_status == "POSITION_COMMITTED" or bool(final.get("position_opened")):
                mode_daily["position_committed"] += 1
            elif stage == "ENTRY_GATE" and allowed is True:
                mode_daily["blocked_after_brain"] += 1
        else:
            mode_daily["final_outcome_unknown"] += 1

        if timestamp:
            slot = floor(timestamp.timestamp() / 300)
            window_keys.add((str(record.get("symbol") or "").upper(), mode, slot))

    # A five-minute symbol/mode window is only a de-duplication aid. It is not
    # proof that all captures in the window represent the same setup.
    for symbol, mode, slot in window_keys:
        day = datetime.fromtimestamp(slot * 300, tz=timezone.utc).date().isoformat()
        if day in daily:
            daily[day]["approximate_symbol_mode_5m_windows"] += 1

    return {
        "available": True,
        "mode": "PAPER_ONLY",
        "funnel_version": FUNNEL_VERSION,
        "capture_records": len(eligible),
        "approximate_symbol_mode_5m_windows": len(window_keys),
        "by_mode": by_mode,
        "by_final_status": dict(sorted(final_status_counts.items())),
        "by_failed_gate": dict(sorted(failed_gate_counts.items())),
        "daily": dict(sorted(daily.items())),
        "recent": sorted(
            eligible,
            key=lambda item: (
                _record_timestamp(item) or datetime.min.replace(tzinfo=timezone.utc)
            ),
            reverse=True,
        )[:30],
        "interpretation": {
            "capture_records": "Unique capture_id decisions; repeated scans can still represent the same market setup.",
            "approximate_symbol_mode_5m_windows": "Symbol/mode captures grouped into five-minute windows; an approximation, not independent trades.",
            "final_outcome_unknown": "Older Brain records without a persisted final disposition, not assumed to be failed or executed.",
            "paper_only": True,
            "trading_logic_changed": False,
        },
    }


__all__ = [
    "FUNNEL_VERSION",
    "build_entry_funnel_record",
    "build_entry_funnel_report",
]
