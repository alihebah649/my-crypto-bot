"""Aggregate closed Paper outcomes for evidence-based diagnostics.

This module is read-only and intentionally returns aggregates, not raw trade
records. It does not affect strategy, risk, Trade Manager, exits, or execution.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Any


_SCORE_THRESHOLDS = {"SCALP": 65.0, "SWING": 80.0}


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if result == result and result not in (float("inf"), float("-inf")) else None


def _label(value: Any) -> str:
    result = str(value or "").strip().upper()
    return result if result else "UNKNOWN"


def _selected_score(record: Mapping[str, Any]) -> float | None:
    strategy = _mapping(record.get("strategy"))
    mode = _label(record.get("trade_mode"))
    key = "scalp_score" if mode == "SCALP" else "swing_score" if mode == "SWING" else "score"
    score = _number(strategy.get(key))
    if score is None:
        score = _number(strategy.get("score"))
    return score


def _score_band(record: Mapping[str, Any]) -> str:
    score = _selected_score(record)
    if score is None:
        return "UNKNOWN"
    mode = _label(record.get("trade_mode"))
    threshold = _SCORE_THRESHOLDS.get(mode)
    if threshold is None:
        if score < 65:
            return "BELOW_65"
        if score < 80:
            return "65_TO_79"
        if score < 85:
            return "80_TO_84"
        return "85_PLUS"
    if score < threshold:
        return "BELOW_THRESHOLD"
    if score < threshold + 5:
        return "AT_THRESHOLD_TO_PLUS4"
    if score < threshold + 10:
        return "THRESHOLD_PLUS5_TO_PLUS9"
    return "THRESHOLD_PLUS10_OR_MORE"


def _pattern(record: Mapping[str, Any]) -> str:
    for value in (
        _mapping(record.get("entry_forensics")).get("pattern_family"),
        _mapping(record.get("strategy")).get("pattern"),
        _mapping(record.get("entry_v2")).get("setup_type"),
    ):
        if value:
            return _label(value)
    return "UNKNOWN"


def _market_regime(record: Mapping[str, Any]) -> str:
    regime = _mapping(record.get("regime"))
    market = regime.get("market") or regime.get("symbol")
    return _label(market)


def _aggregate(records: list[Mapping[str, Any]]) -> dict[str, Any]:
    pnl_values = [(row, _number(row.get("realized_pnl"))) for row in records]
    known_pnl = [(row, pnl) for row, pnl in pnl_values if pnl is not None]
    wins = [pnl for _, pnl in known_pnl if pnl > 0]
    losses = [pnl for _, pnl in known_pnl if pnl < 0]
    flats = [pnl for _, pnl in known_pnl if pnl == 0]
    positive_total = sum(wins)
    negative_total = sum(losses)
    net_total = sum(pnl for _, pnl in known_pnl)

    gross_values = [_number(row.get("gross_pnl")) for row in records]
    fee_values = [_number(row.get("fees")) for row in records]
    gross_known = [value for value in gross_values if value is not None]
    fees_known = [value for value in fee_values if value is not None]

    valid_stops: list[float] = []
    for row in records:
        forensics = _mapping(row.get("entry_forensics"))
        stop = _number(forensics.get("stop_distance_percent"))
        if forensics.get("stop_distance_valid") is True and stop is not None and stop > 0:
            valid_stops.append(stop)

    holdings = [
        value
        for value in (_number(row.get("holding_seconds")) for row in records)
        if value is not None and value >= 0
    ]
    decided = len(wins) + len(losses)

    return {
        "records": len(records),
        "pnl_records": len(known_pnl),
        "records_missing_net_pnl": len(records) - len(known_pnl),
        "wins": len(wins),
        "losses": len(losses),
        "flat": len(flats),
        "win_rate_percent": round(len(wins) / decided * 100.0, 2) if decided else None,
        "gross_pnl": round(sum(gross_known), 6) if gross_known else None,
        "fees": round(sum(fees_known), 6) if fees_known else None,
        "net_pnl": round(net_total, 6) if known_pnl else None,
        "avg_net_pnl_per_trade": round(net_total / len(known_pnl), 6) if known_pnl else None,
        "avg_win_net_pnl": round(positive_total / len(wins), 6) if wins else None,
        "avg_loss_net_pnl": round(negative_total / len(losses), 6) if losses else None,
        "profit_factor": round(positive_total / abs(negative_total), 4) if negative_total < 0 else None,
        "avg_fee": round(sum(fees_known) / len(fees_known), 6) if fees_known else None,
        "valid_stop_distance_records": len(valid_stops),
        "avg_stop_distance_percent": round(sum(valid_stops) / len(valid_stops), 6) if valid_stops else None,
        "avg_holding_minutes": round(sum(holdings) / len(holdings) / 60.0, 3) if holdings else None,
    }


def _grouped(
    records: list[Mapping[str, Any]],
    key_fn,
) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[_label(key_fn(record))].append(record)
    return {
        key: _aggregate(grouped[key])
        for key in sorted(grouped, key=lambda item: (-len(grouped[item]), item))
    }


def build_paper_outcome_analysis(
    records: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Return overall and factor-level outcomes for already-closed Paper trades.

    Groupings are diagnostic only. Score bands are relative to the preserved
    SCALP=65 and SWING=80 thresholds and never imply a recommendation to change
    those thresholds.
    """
    rows = [record for record in records if isinstance(record, Mapping)]
    entry_reason_records: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for record in rows:
        reasons: set[str] = set()
        v2_reasons = _mapping(record.get("entry_v2")).get("reasons", [])
        if isinstance(v2_reasons, (list, tuple, set)):
            reasons.update(_label(value) for value in v2_reasons if value)
        forensics = _mapping(record.get("entry_forensics"))
        recovery_reasons = forensics.get("recovery_trigger_reasons", [])
        if isinstance(recovery_reasons, (list, tuple, set)):
            reasons.update(_label(value) for value in recovery_reasons if value)
        scalp_reasons = _mapping(record.get("strategy")).get("scalp_gate_reasons", [])
        if isinstance(scalp_reasons, (list, tuple, set)):
            reasons.update(_label(value) for value in scalp_reasons if value)
        for reason in reasons:
            entry_reason_records[reason].append(record)

    outcome_totals = _aggregate(rows)
    return {
        "schema_version": 1,
        "report_type": "PAPER_CLOSED_OUTCOME_ANALYSIS",
        "record_count": len(rows),
        "totals": outcome_totals,
        "by_trade_mode": _grouped(rows, lambda row: row.get("trade_mode")),
        "by_market_data_source": _grouped(
            rows,
            lambda row: row.get("market_data_source")
            or _mapping(row.get("strategy")).get("market_data_source"),
        ),
        "by_close_reason": _grouped(rows, lambda row: row.get("close_reason")),
        "by_entry_score_band": _grouped(rows, _score_band),
        "by_pattern": _grouped(rows, _pattern),
        "by_market_regime": _grouped(rows, _market_regime),
        # A trade can have multiple reasons; these reason groups intentionally
        # overlap and therefore must not be summed as if they were disjoint.
        "by_entry_reason": {
            key: _aggregate(entry_reason_records[key])
            for key in sorted(entry_reason_records, key=lambda item: (-len(entry_reason_records[item]), item))
        },
        "data_quality": {
            "records_missing_trade_mode": sum(1 for row in rows if not row.get("trade_mode")),
            "records_missing_market_data_source": sum(
                1
                for row in rows
                if not (
                    row.get("market_data_source")
                    or _mapping(row.get("strategy")).get("market_data_source")
                )
            ),
            "records_missing_entry_context": sum(1 for row in rows if not row.get("entry_context_available")),
        },
    }


__all__ = ["build_paper_outcome_analysis"]
