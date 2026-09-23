"""Binding helpers for entry-cycle Brain Shadow evidence.

These helpers only attach an already-evaluated Brain Shadow observation to the
Paper position carrying the same Entry v2 capture identity and lane. They do
not alter strategy, risk, execution, or position lifecycle decisions.
"""
from __future__ import annotations

from typing import Any, Mapping


def attach_brain_shadow_entry(repository: Any, record: Mapping[str, Any]) -> str | None:
    """Attach one entry-cycle Brain Shadow record to its matching open position.

    The match is intentionally keyed by Entry v2 capture_id plus trade_mode so
    dual-lane SCALP/SWING observations cannot cross-contaminate each other.
    """
    capture_id = str(record.get("capture_id") or "")
    lane = str(
        record.get("trade_mode")
        or (record.get("context", {}) or {}).get("trade_mode")
        or ""
    ).upper()
    if not capture_id or lane not in {"SCALP", "SWING"}:
        return None

    try:
        positions = list(repository.get_open_positions() or [])
    except Exception:
        return None

    for position in positions:
        metadata = getattr(position, "entry_metadata", None)
        if not isinstance(metadata, dict):
            continue
        position_capture_id = str(metadata.get("entry_v2_shadow_capture_id") or "")
        position_lane = str(
            metadata.get("trade_mode")
            or metadata.get("entry_v2_shadow_trade_mode")
            or ""
        ).upper()
        if position_capture_id != capture_id or position_lane != lane:
            continue

        metadata["brain_shadow_entry"] = dict(record)
        metadata["brain_shadow_entry_captured_at"] = record.get("timestamp")
        try:
            repository.update(position)
        except Exception:
            return None
        return str(getattr(position, "position_id", "") or "") or None

    return None


__all__ = ["attach_brain_shadow_entry"]
