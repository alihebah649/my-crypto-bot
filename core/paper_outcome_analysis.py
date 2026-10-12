"""Aggregate closed Paper outcomes for evidence-based diagnostics.

This module is read-only and intentionally returns aggregates, not raw trade
records. It does not affect strategy, risk, Trade Manager, exits, or execution.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from collections.abc import Iterable, Mapping
from typing import Any


_SCORE_THRESHOLDS = {"SCALP": 65.0, "SWING": 80.0}
_VALID_RECOVERY_TRIGGER_REASONS = frozenset({
    "5M_RSI_RISING",
    "5M_PRICE_RECOVERY",
    "5M_BULLISH_BODY",
})


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


_UNAVAILABLE_LABELS = frozenset({"", "UNKNOWN", "NONE", "NULL", "N/A"})


def _has_known_value(value: Any) -> bool:
    return str(value or "").strip().upper() not in _UNAVAILABLE_LABELS


def _first_known(*values: Any) -> Any:
    for value in values:
        if _has_known_value(value):
            return value
    return None


def _utc_day(value: Any) -> str | None:
    """Return a UTC calendar day from a captured ISO timestamp or epoch value."""
    if value is None or value == "":
        return None
    try:
        if isinstance(value, str):
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc).date().isoformat()
        numeric = _number(value)
        if numeric is None:
            return None
        # Accommodate both epoch seconds and milliseconds in persisted evidence.
        if abs(numeric) >= 1_000_000_000_000:
            numeric /= 1000.0
        return datetime.fromtimestamp(numeric, tz=timezone.utc).date().isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _entry_day(record: Mapping[str, Any]) -> str | None:
    return _utc_day(
        record.get("opened_at_utc")
        if _has_known_value(record.get("opened_at_utc"))
        else record.get("opened_at")
    )


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
    """Use captured regime labels, then fall back to the captured MTF facts.

    Older Paper records often preserve MTF bias/strength while leaving
    market_regime and symbol_regime unset. This fallback is diagnostic only:
    it classifies saved context and never recalculates a live trading decision.
    """
    regime = _mapping(record.get("regime"))
    for value in (regime.get("market"), regime.get("symbol")):
        label = _label(value)
        if label != "UNKNOWN":
            return label

    # Mirror the Brain regime hierarchy when an explicit higher-timeframe
    # directional flag was captured.
    if regime.get("mtf_higher_timeframes_bearish") is True:
        return "BEAR"
    if regime.get("mtf_higher_timeframes_bullish") is True:
        return "BULL"

    bias = _label(regime.get("mtf_bias"))
    if bias in {"BULL", "BULLISH", "UPTREND"}:
        return "BULL"
    if bias in {"BEAR", "BEARISH", "DOWNTREND"}:
        return "BEAR"
    if bias in {"NEUTRAL", "SIDEWAYS", "TRANSITION", "MIXED"}:
        return "TRANSITION"

    mtf_net = _number(regime.get("mtf_net"))
    if mtf_net is not None:
        if mtf_net > 0:
            return "BULL"
        if mtf_net < 0:
            return "BEAR"
        return "TRANSITION"
    return "UNKNOWN"


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


def _raw_reason_values(record: Mapping[str, Any], source: str) -> set[str]:
    """Return captured tags unchanged by source, for compatibility reporting."""
    if source == "entry_v2":
        values = _mapping(record.get("entry_v2")).get("reasons", [])
    elif source == "recovery_trigger":
        values = _mapping(record.get("entry_forensics")).get("recovery_trigger_reasons", [])
    elif source == "scalp_gate":
        values = _mapping(record.get("strategy")).get("scalp_gate_reasons", [])
    else:
        return set()
    if not isinstance(values, (list, tuple, set)):
        return set()
    return {_label(value) for value in values if value}


def _reason_values(record: Mapping[str, Any], source: str) -> set[str]:
    """Return a source-specific group, rejecting foreign tags from trigger data."""
    values = _raw_reason_values(record, source)
    if source == "recovery_trigger":
        return values & _VALID_RECOVERY_TRIGGER_REASONS
    return values


def _grouped_reasons(
    records: list[Mapping[str, Any]],
    source: str,
) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        for reason in _reason_values(record, source):
            grouped[reason].append(record)
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
    those thresholds. Reason groups overlap because a trade may carry multiple
    tags, and the source-specific groups must not be summed.
    """
    rows = [record for record in records if isinstance(record, Mapping)]
    regimes = [_market_regime(row) for row in rows]
    return {
        "schema_version": 1,
        "report_type": "PAPER_CLOSED_OUTCOME_ANALYSIS",
        "record_count": len(rows),
        "totals": _aggregate(rows),
        # Schema cohorts distinguish recent forensic captures from older rows
        # whose source/stop metadata was never persisted.
        "by_evidence_schema_version": _grouped(rows, lambda row: row.get("schema_version")),
        # Group by entry/open date (not close date) so the cohort reflects the
        # market-data policy at the time the signal was opened.
        "by_entry_day_utc": _grouped(rows, _entry_day),
        "by_entry_day_and_trade_mode": _grouped_pairs(
            rows, _entry_day, lambda row: row.get("trade_mode")
        ),
        "by_entry_day_and_market_data_source": _grouped_pairs(
            rows,
            _entry_day,
            lambda row: _first_known(
                row.get("market_data_source"),
                _mapping(row.get("strategy")).get("market_data_source"),
            ),
        ),
        "by_trade_mode": _grouped(rows, lambda row: row.get("trade_mode")),
        "by_market_data_source": _grouped(
            rows,
            lambda row: _first_known(
                row.get("market_data_source"),
                _mapping(row.get("strategy")).get("market_data_source"),
            ),
        ),
        "by_execution_market_data_source": _grouped(
            rows, lambda row: row.get("execution_market_data_source")
        ),
        "by_close_reason": _grouped(rows, lambda row: row.get("close_reason")),
        "by_trade_mode_and_market_data_source": _grouped_pairs(
            rows,
            lambda row: row.get("trade_mode"),
            lambda row: _first_known(
                row.get("market_data_source"),
                _mapping(row.get("strategy")).get("market_data_source"),
            ),
        ),
        "by_trade_mode_and_execution_market_data_source": _grouped_pairs(
            rows,
            lambda row: row.get("trade_mode"),
            lambda row: row.get("execution_market_data_source"),
        ),
        "by_trade_mode_and_close_reason": _grouped_pairs(
            rows,
            lambda row: row.get("trade_mode"),
            lambda row: row.get("close_reason"),
        ),
        "by_entry_score_band": _grouped(rows, _score_band),
        "by_pattern": _grouped(rows, _pattern),
        "by_market_regime": _grouped(rows, _market_regime),
        # Backward-compatible union of three different tag sources. Use the
        # source-specific groups below to tell these classes apart.
        "by_entry_reason": _grouped_combined_reasons(rows),
        "by_entry_v2_reason": _grouped_reasons(rows, "entry_v2"),
        "by_recovery_trigger_reason": _grouped_reasons(rows, "recovery_trigger"),
        "by_scalp_gate_reason": _grouped_reasons(rows, "scalp_gate"),
        "data_quality": {
            "records_missing_trade_mode": sum(1 for row in rows if not row.get("trade_mode")),
            "records_missing_schema_version": sum(1 for row in rows if row.get("schema_version") is None),
            "records_missing_entry_opened_at": sum(1 for row in rows if _entry_day(row) is None),
            "records_missing_market_data_source": sum(
                1
                for row in rows
                if not _has_known_value(
                    _first_known(
                        row.get("market_data_source"),
                        _mapping(row.get("strategy")).get("market_data_source"),
                    )
                )
            ),
            "records_missing_execution_market_data_source": sum(
                1
                for row in rows
                if not _has_known_value(row.get("execution_market_data_source"))
            ),
            "records_without_frozen_entry_stop": sum(
                1
                for row in rows
                if _mapping(row.get("entry_forensics")).get("stop_distance_source")
                != "ENTRY_METADATA"
            ),
            "records_missing_strategy_snapshot_source": sum(
                1
                for row in rows
                if not _has_known_value(
                    _mapping(row.get("entry_forensics")).get("strategy_snapshot_source")
                )
            ),
            "records_missing_entry_context": sum(1 for row in rows if not row.get("entry_context_available")),
            "records_missing_market_regime": sum(1 for regime in regimes if regime == "UNKNOWN"),
            "records_with_unrecognized_recovery_trigger_reasons": sum(
                1
                for row in rows
                if _raw_reason_values(row, "recovery_trigger") - _VALID_RECOVERY_TRIGGER_REASONS
            ),
        },
    }


def _grouped_pairs(
    records: list[Mapping[str, Any]],
    left_key_fn,
    right_key_fn,
) -> dict[str, dict[str, Any]]:
    """Aggregate a cross-tab without exporting raw closed-trade records."""
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        pair = (_label(left_key_fn(record)), _label(right_key_fn(record)))
        grouped[pair].append(record)
    ordered = sorted(grouped, key=lambda pair: (-len(grouped[pair]), pair[0], pair[1]))
    return {
        f"{left}::{right}": _aggregate(grouped[(left, right)])
        for left, right in ordered
    }


def _grouped_combined_reasons(records: list[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Legacy combined reason grouping, retained for API compatibility."""
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        reasons = (
            _raw_reason_values(record, "entry_v2")
            | _raw_reason_values(record, "recovery_trigger")
            | _raw_reason_values(record, "scalp_gate")
        )
        for reason in reasons:
            grouped[reason].append(record)
    return {
        key: _aggregate(grouped[key])
        for key in sorted(grouped, key=lambda item: (-len(grouped[item]), item))
    }


__all__ = ["build_paper_outcome_analysis"]
