"""Descriptive outcome analysis for durable Brain shadow evidence.

No causal claim is made. The module only joins a Brain observation to an actual
Paper position that carries the same Entry v2 capture identity and lane.
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


def _metadata(position: Any) -> Mapping[str, Any]:
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


def _add(bucket: dict[str, Any], position: Any) -> None:
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


def _key(capture_id: Any, lane: Any) -> tuple[str, str]:
    return str(capture_id or ""), str(lane or "UNKNOWN").upper()


def analyze_brain_shadow_outcomes(
    brain_records: Iterable[Mapping[str, Any]],
    positions: Iterable[Any],
) -> dict[str, Any]:
    records = [record for record in brain_records if isinstance(record, Mapping)]
    position_list = list(positions)

    record_by_key: dict[tuple[str, str], Mapping[str, Any]] = {}
    for record in records:
        capture_id = record.get("capture_id")
        lane = record.get("trade_mode") or (record.get("context", {}) or {}).get("trade_mode")
        if capture_id:
            record_by_key[_key(capture_id, lane)] = record

    by_market_regime: dict[str, dict[str, Any]] = defaultdict(_bucket)
    by_symbol_regime: dict[str, dict[str, Any]] = defaultdict(_bucket)
    by_lane_market_regime: dict[str, dict[str, Any]] = defaultdict(_bucket)
    by_brain_action: dict[str, dict[str, Any]] = defaultdict(_bucket)
    by_brain_reason: dict[str, dict[str, Any]] = defaultdict(_bucket)

    matched_position_ids: set[str] = set()
    unmatched_position_ids: list[str] = []
    unmatched_brain_records: set[str] = set()
    rejected_legacy_rows: list[dict[str, Any]] = []

    for position in position_list:
        metadata = _metadata(position)
        capture_id = metadata.get("entry_v2_shadow_capture_id")
        lane = metadata.get("trade_mode")
        if not capture_id:
            continue
        record = record_by_key.get(_key(capture_id, lane))
        if record is None:
            unmatched_position_ids.append(str(_value(position, "position_id", "")))
            continue

        context = record.get("context", {}) or {}
        market_regime = str(context.get("market_regime") or "UNKNOWN").upper()
        symbol_regime = str(context.get("symbol_regime") or "UNKNOWN").upper()
        lane_name = str(record.get("trade_mode") or lane or "UNKNOWN").upper()
        brain_action = str(record.get("brain_action") or "HOLD").upper()
        brain_reason = str(record.get("brain_reason") or "UNKNOWN")

        position_id = str(_value(position, "position_id", ""))
        if position_id:
            matched_position_ids.add(position_id)

        _add(by_market_regime[market_regime], position)
        _add(by_symbol_regime[symbol_regime], position)
        _add(by_lane_market_regime[f"{lane_name}|{market_regime}"], position)
        _add(by_brain_action[brain_action], position)
        _add(by_brain_reason[brain_reason], position)

        if (
            str(record.get("strategy_action") or "HOLD").upper() == "BUY"
            and brain_action != "BUY"
        ):
            realized = _float(_value(position, "realized_pnl", 0.0))
            rejected_legacy_rows.append({
                "position_id": position_id,
                "capture_id": str(capture_id),
                "symbol": str(record.get("symbol") or _value(position, "symbol", "")).upper(),
                "trade_mode": lane_name,
                "market_regime": market_regime,
                "symbol_regime": symbol_regime,
                "brain_reason": brain_reason,
                "status": _status_name(position),
                "realized_pnl": realized,
                "fees": _float(_value(position, "total_fees", 0.0)),
            })

    matched_record_keys = {
        _key(
            metadata.get("entry_v2_shadow_capture_id"),
            metadata.get("trade_mode"),
        )
        for position in position_list
        for metadata in [_metadata(position)]
        if metadata.get("entry_v2_shadow_capture_id")
    }
    for record in records:
        capture_id = record.get("capture_id")
        lane = record.get("trade_mode") or (record.get("context", {}) or {}).get("trade_mode")
        key = _key(capture_id, lane)
        if capture_id and key not in matched_record_keys:
            unmatched_brain_records.add(f"{capture_id}|{str(lane or 'UNKNOWN').upper()}")

    rejected_closed = [row for row in rejected_legacy_rows if row["status"] == "CLOSED"]
    rejected_open = [row for row in rejected_legacy_rows if row["status"] in _ACTIVE_STATUSES]

    return {
        "schema_version": 1,
        "coverage": {
            "brain_records": len(records),
            "matched_positions": len(matched_position_ids),
            "unmatched_positions": len([x for x in unmatched_position_ids if x]),
            "unmatched_brain_records": len(unmatched_brain_records),
        },
        "legacy_executed_brain_rejected": {
            "positions": len(rejected_legacy_rows),
            "closed_positions": len(rejected_closed),
            "open_positions": len(rejected_open),
            "wins": sum(1 for row in rejected_closed if row["realized_pnl"] > 0),
            "losses": sum(1 for row in rejected_closed if row["realized_pnl"] < 0),
            "flat": sum(1 for row in rejected_closed if row["realized_pnl"] == 0),
            "realized_pnl": sum(row["realized_pnl"] for row in rejected_closed),
            "fees": sum(row["fees"] for row in rejected_closed),
        },
        "by_market_regime": dict(by_market_regime),
        "by_symbol_regime": dict(by_symbol_regime),
        "by_lane_market_regime": dict(by_lane_market_regime),
        "by_brain_action": dict(by_brain_action),
        "by_brain_reason": dict(by_brain_reason),
        "rejected_execution_rows": rejected_legacy_rows[-100:],
    }


__all__ = ["analyze_brain_shadow_outcomes"]
