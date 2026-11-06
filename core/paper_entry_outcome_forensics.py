"""Linked, read-only forensics for Paper entry captures and closed outcomes.

Joins MAIN outcomes by Entry-v2 capture_id and hosted labs by position_id.
It computes empirical execution economics; it never changes a trade decision.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from math import isfinite
from typing import Any


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if isfinite(result) else None


def _first_number(*values: Any) -> float | None:
    for value in values:
        result = _number(value)
        if result is not None:
            return result
    return None


def _percent(value: float | None) -> float | None:
    return round(value, 4) if value is not None and isfinite(value) else None


def _price(value: Any) -> float | None:
    result = _number(value)
    return result if result is not None and result > 0 else None


def _capture_id_from_outcome(outcome: Mapping[str, Any]) -> str:
    entry_v2 = _mapping(outcome.get("entry_v2"))
    chain = _mapping(outcome.get("entry_decision_chain"))
    chain_v2 = _mapping(chain.get("entry_v2"))
    brain = _mapping(outcome.get("brain"))
    return str(
        entry_v2.get("capture_id")
        or chain_v2.get("capture_id")
        or brain.get("capture_id")
        or ""
    ).strip()


def _capture_index(
    captures: list[Mapping[str, Any]],
) -> tuple[dict[str, Mapping[str, Any]], dict[str, Mapping[str, Any]]]:
    by_id: dict[str, Mapping[str, Any]] = {}
    by_position: dict[str, Mapping[str, Any]] = {}
    for capture in captures:
        capture_id = str(capture.get("capture_id") or "").strip()
        position_id = str(capture.get("position_id") or "").strip()
        if capture_id:
            by_id[capture_id] = capture
        if position_id:
            by_position[position_id] = capture
    return by_id, by_position


def _capture_parts(capture: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    candidate = _mapping(capture.get("candidate"))
    legacy = _mapping(capture.get("legacy_result"))
    scenario = _mapping(capture.get("entry_scenario"))
    scenario_risk = _mapping(scenario.get("risk"))
    return candidate, legacy, scenario, scenario_risk


def _joined_row(
    venue: str,
    outcome: Mapping[str, Any],
    capture: Mapping[str, Any],
) -> dict[str, Any]:
    candidate, legacy, scenario, scenario_risk = _capture_parts(capture)
    outcome_v2 = _mapping(outcome.get("entry_v2"))
    chain_v2 = _mapping(_mapping(outcome.get("entry_decision_chain")).get("entry_v2"))
    capture_v2 = _mapping(capture.get("v2_decision"))

    mode = str(
        outcome.get("trade_mode")
        or candidate.get("trade_mode")
        or scenario.get("trade_mode")
        or legacy.get("trade_mode")
        or "UNKNOWN"
    ).upper()
    entry = _price(
        outcome.get("entry_price")
        or candidate.get("entry_price")
        or legacy.get("price")
    )
    if entry is None:
        entry = _price(scenario_risk.get("entry_price"))

    stop_source = str(
        _mapping(outcome.get("entry_forensics")).get("stop_distance_source") or ""
    ).upper()
    if stop_source == "ENTRY_METADATA":
        stop = _price(outcome.get("entry_stop_loss"))
    else:
        stop = _price(candidate.get("stop_loss"))
        if stop is None:
            stop = _price(outcome.get("entry_stop_loss"))
    if stop is None:
        stop = _price(scenario_risk.get("atr_stop_loss") or outcome.get("stop_loss"))

    target = _price(
        scenario_risk.get("target_price")
        or outcome_v2.get("target_price")
        or candidate.get("target_price")
    )
    economics = _mapping(
        capture.get("entry_economics") or outcome.get("entry_economics")
    )
    risk = _mapping(scenario_risk)
    strategy = _mapping(outcome.get("strategy"))
    atr = _first_number(
        legacy.get("atr"),
        strategy.get("atr"),
        candidate.get("atr"),
    )
    quantity = _first_number(outcome.get("quantity"))
    gross_pnl = _first_number(outcome.get("gross_pnl"))
    net_pnl = _first_number(outcome.get("realized_pnl"))
    fees = _first_number(outcome.get("fees"))
    entry_v2_approved = capture_v2.get(
        "approved",
        outcome_v2.get("approved", chain_v2.get("approved")),
    )
    if entry_v2_approved is not None:
        entry_v2_approved = bool(entry_v2_approved)

    score = _first_number(
        candidate.get("score"),
        legacy.get("score"),
        legacy.get("scalp_score") if mode == "SCALP" else None,
        legacy.get("swing_score") if mode == "SWING" else None,
        strategy.get("score"),
        strategy.get("scalp_score") if mode == "SCALP" else None,
        strategy.get("swing_score") if mode == "SWING" else None,
    )
    expected_rr = _first_number(
        economics.get("reward_risk"),
        risk.get("reward_risk"),
        outcome_v2.get("reward_risk"),
    )
    entry_price = entry or 0.0
    stop_distance = (
        entry_price - stop
        if entry is not None and stop is not None and stop < entry_price
        else None
    )
    risk_percent = _first_number(economics.get("risk_percent"))
    if risk_percent is None and stop_distance is not None and entry_price > 0:
        risk_percent = stop_distance / entry_price * 100.0
    stop_atr_multiple = (
        stop_distance / atr
        if stop_distance is not None and atr is not None and atr > 0
        else None
    )
    planned_net_reward_percent = _first_number(economics.get("net_reward_percent"))
    expected_net_rr = (
        planned_net_reward_percent / risk_percent
        if planned_net_reward_percent is not None
        and risk_percent is not None
        and risk_percent > 0
        else None
    )
    quote_notional = entry_price * quantity if quantity is not None else None
    fee_percent = (
        fees / quote_notional * 100.0
        if fees is not None and quote_notional is not None and quote_notional > 0
        else None
    )
    realized_r = (
        net_pnl / (stop_distance * quantity)
        if net_pnl is not None
        and stop_distance is not None
        and quantity is not None
        and stop_distance > 0
        and quantity > 0
        else None
    )

    highest = _price(outcome.get("highest_price"))
    max_profit_percent = _number(outcome.get("max_profit_percent"))
    if highest is not None and entry is not None and quantity is not None:
        gross_mfe = max(0.0, highest - entry) * quantity
        net_mfe = gross_mfe - (fees or 0.0)
        mfe_source = "HIGHEST_PRICE_MINUS_RECORDED_FEES"
    elif max_profit_percent is not None and quote_notional is not None:
        gross_mfe = quote_notional * max(0.0, max_profit_percent) / 100.0
        net_mfe = gross_mfe - (fees or 0.0)
        mfe_source = "MAX_PROFIT_PERCENT_MINUS_RECORDED_FEES"
    else:
        gross_mfe = None
        net_mfe = None
        mfe_source = "UNAVAILABLE"

    target_reached = (
        highest >= target
        if highest is not None and target is not None
        else None
    )
    close_reason = str(outcome.get("close_reason") or "UNKNOWN").upper()
    symbol = str(outcome.get("symbol") or candidate.get("symbol") or capture.get("symbol") or "UNKNOWN").upper()
    return {
        "venue": str(venue).upper(),
        "symbol": symbol,
        "trade_mode": mode,
        "score": score,
        "entry_price": entry,
        "entry_stop_loss": stop,
        "target_price": target,
        "close_reason": close_reason,
        "gross_pnl": gross_pnl,
        "net_pnl": net_pnl,
        "fees": fees,
        "fee_percent_of_entry_notional": fee_percent,
        "expected_rr": expected_rr,
        "expected_net_rr_after_fees": expected_net_rr,
        "planned_risk_percent": risk_percent,
        "planned_net_reward_percent": planned_net_reward_percent,
        "stop_atr_multiple": stop_atr_multiple,
        "realized_r_multiple_net": realized_r,
        "highest_price": highest,
        "max_profit_percent": max_profit_percent,
        "net_mfe": net_mfe,
        "mfe_source": mfe_source,
        "target_reached": target_reached,
        "entry_v2_approved_shadow": entry_v2_approved,
        "entry_v2_decision_shadow": str(
            capture_v2.get("decision")
            or outcome_v2.get("decision")
            or chain_v2.get("decision")
            or "UNAVAILABLE"
        ).upper(),
        "entry_v2_failed_gate_shadow": str(
            capture_v2.get("failed_gate")
            or outcome_v2.get("failed_gate")
            or chain_v2.get("failed_gate")
            or "NONE"
        ).upper(),
        "setup_type": str(
            capture_v2.get("setup_type")
            or scenario.get("setup_type")
            or "UNKNOWN"
        ).upper(),
        "market_regime": str(
            _mapping(outcome.get("regime")).get("market")
            or _mapping(scenario.get("market")).get("regime")
            or "UNKNOWN"
        ).upper(),
        "rsi5m": _first_number(legacy.get("rsi5m"), strategy.get("rsi5m")),
        "volume_ratio_5m": _first_number(
            legacy.get("volume_ratio_5m"),
            strategy.get("volume_ratio_5m"),
        ),
        "atr_percent_of_entry": _first_number(
            _mapping(outcome.get("entry_forensics")).get("atr_percent_of_entry"),
            (atr / entry * 100.0) if atr is not None and entry is not None and entry > 0 else None,
        ),
    }


def _aggregate(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    wins = [row for row in rows if (_number(row.get("net_pnl")) or 0.0) > 0]
    losses = [row for row in rows if (_number(row.get("net_pnl")) or 0.0) < 0]
    flats = len(rows) - len(wins) - len(losses)
    net_values = [_number(row.get("net_pnl")) for row in rows]
    gross_values = [_number(row.get("gross_pnl")) for row in rows]
    fee_values = [_number(row.get("fees")) for row in rows]
    positive_sum = sum(value or 0.0 for value in net_values if value is not None and value > 0)
    negative_sum = abs(sum(value or 0.0 for value in net_values if value is not None and value < 0))
    valid_rr = [_number(row.get("expected_rr")) for row in rows]
    valid_net_rr = [_number(row.get("expected_net_rr_after_fees")) for row in rows]
    valid_realized_r = [_number(row.get("realized_r_multiple_net")) for row in rows]
    valid_stop_atr = [_number(row.get("stop_atr_multiple")) for row in rows]
    valid_mfe = [_number(row.get("net_mfe")) for row in rows]
    losing_rows = [row for row in rows if (_number(row.get("net_pnl")) or 0.0) < 0]
    losing_with_positive_mfe = [
        row for row in losing_rows
        if _number(row.get("net_mfe")) is not None and float(row["net_mfe"]) > 0
    ]
    target_rows = [row for row in rows if row.get("target_reached") is not None]
    target_hits = [row for row in target_rows if row.get("target_reached") is True]

    def mean(values: list[float | None]) -> float | None:
        clean = [value for value in values if value is not None and isfinite(value)]
        return round(sum(clean) / len(clean), 4) if clean else None

    return {
        "closed_trades": len(rows),
        "wins": len(wins),
        "losses": len(losses),
        "flat": flats,
        "win_rate_percent": round(len(wins) / len(rows) * 100.0, 2) if rows else None,
        "net_pnl_after_fees": round(sum(value or 0.0 for value in net_values), 6),
        "gross_pnl": round(sum(value or 0.0 for value in gross_values), 6),
        "fees": round(sum(value or 0.0 for value in fee_values), 6),
        "profit_factor_net": round(positive_sum / negative_sum, 4) if negative_sum else (None if not positive_sum else "INF"),
        "average_win_net": mean([_number(row.get("net_pnl")) for row in wins]),
        "average_loss_net": mean([_number(row.get("net_pnl")) for row in losses]),
        "average_expected_rr": mean(valid_rr),
        "average_expected_net_rr_after_fees": mean(valid_net_rr),
        "average_realized_r_multiple_net": mean(valid_realized_r),
        "average_stop_atr_multiple": mean(valid_stop_atr),
        "average_fee_percent_of_entry_notional": mean([
            _number(row.get("fee_percent_of_entry_notional")) for row in rows
        ]),
        "target_observed_trades": len(target_rows),
        "target_reached": len(target_hits),
        "target_reached_percent_of_observed": (
            round(len(target_hits) / len(target_rows) * 100.0, 2) if target_rows else None
        ),
        "losers_with_positive_net_favorable_excursion": len(losing_with_positive_mfe),
        "losers_with_positive_net_favorable_excursion_percent": (
            round(len(losing_with_positive_mfe) / len(losing_rows) * 100.0, 2)
            if losing_rows else None
        ),
        "losers_without_observed_positive_net_excursion": (
            len(losing_rows) - len(losing_with_positive_mfe)
        ),
        "average_net_favorable_excursion_usd": mean(valid_mfe),
    }


def _group(rows: list[Mapping[str, Any]], key: str) -> dict[str, Any]:
    buckets: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        value = row.get(key)
        label = "UNKNOWN" if value is None or value == "" else str(value).upper()
        buckets[label].append(row)
    return {
        label: _aggregate(buckets[label])
        for label in sorted(buckets)
    }


def build_linked_entry_outcome_analysis(
    venue: str,
    outcomes: Iterable[Mapping[str, Any]],
    captures: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Join executed closed trades to their original entry captures, then aggregate."""
    venue_name = str(venue or "").strip().upper()
    if venue_name not in {"MAIN", "BYBIT", "OKX"}:
        raise ValueError(f"unsupported Paper venue: {venue_name or 'EMPTY'}")

    outcome_rows = [row for row in outcomes if isinstance(row, Mapping)]
    capture_rows = [row for row in captures if isinstance(row, Mapping)]
    by_id, by_position = _capture_index(capture_rows)

    joined: list[dict[str, Any]] = []
    unmatched_outcomes: list[Mapping[str, Any]] = []
    matched_capture_ids: set[str] = set()
    matched_position_keys: set[str] = set()

    for outcome in outcome_rows:
        position_id = str(outcome.get("position_id") or "").strip()
        capture_id = _capture_id_from_outcome(outcome)
        capture = by_id.get(capture_id) if capture_id else None
        if capture is None and position_id:
            capture = by_position.get(position_id)
        if capture is None:
            unmatched_outcomes.append(outcome)
            continue
        joined.append(_joined_row(venue_name, outcome, capture))
        matched_capture_id = str(capture.get("capture_id") or "").strip()
        if matched_capture_id:
            matched_capture_ids.add(matched_capture_id)
        if position_id:
            matched_position_keys.add(position_id)

    unmatched_captures = len([
        capture for capture in capture_rows
        if str(capture.get("capture_id") or "").strip() not in matched_capture_ids
        and str(capture.get("position_id") or "").strip() not in matched_position_keys
    ])
    losing_positive_mfe = sorted(
        [
            row for row in joined
            if (_number(row.get("net_pnl")) or 0.0) < 0
            and _number(row.get("net_mfe")) is not None
            and float(row["net_mfe"]) > 0
        ],
        key=lambda row: float(row["net_mfe"]),
        reverse=True,
    )
    worst = sorted(
        [row for row in joined if _number(row.get("net_pnl")) is not None],
        key=lambda row: float(row["net_pnl"]),
    )[:5]
    best = sorted(
        [row for row in joined if _number(row.get("net_pnl")) is not None],
        key=lambda row: float(row["net_pnl"]),
        reverse=True,
    )[:5]

    def public_sample(row: Mapping[str, Any]) -> dict[str, Any]:
        fields = (
            "symbol", "trade_mode", "score", "net_pnl", "fees",
            "expected_rr", "expected_net_rr_after_fees",
            "realized_r_multiple_net", "stop_atr_multiple",
            "net_mfe", "target_reached", "close_reason",
            "entry_v2_approved_shadow", "entry_v2_failed_gate_shadow",
            "market_regime",
        )
        return {key: row.get(key) for key in fields}

    return {
        "schema_version": 1,
        "venue": venue_name,
        "coverage": {
            "outcome_records_read": len(outcome_rows),
            "entry_captures_read": len(capture_rows),
            "matched_closed_trades": len(joined),
            "unmatched_outcomes": len(unmatched_outcomes),
            "unmatched_entry_captures": unmatched_captures,
            "matched_percent_of_outcomes": (
                round(len(joined) / len(outcome_rows) * 100.0, 2)
                if outcome_rows else None
            ),
        },
        "overall": _aggregate(joined),
        "by_trade_mode": _group(joined, "trade_mode"),
        "by_close_reason": _group(joined, "close_reason"),
        "by_entry_v2_shadow_approval": _group(joined, "entry_v2_approved_shadow"),
        "by_entry_v2_shadow_failed_gate": _group(joined, "entry_v2_failed_gate_shadow"),
        "by_market_regime": _group(joined, "market_regime"),
        "losers_with_positive_net_favorable_excursion": [
            public_sample(row) for row in losing_positive_mfe[:10]
        ],
        "worst_trades": [public_sample(row) for row in worst],
        "best_trades": [public_sample(row) for row in best],
        "limitations": [
            "Only closed outcomes in the requested time window are analyzed.",
            "A target hit is inferred from the recorded highest price; it is unavailable when that price was not persisted.",
            "Net favorable excursion subtracts the trade's recorded total fees from the peak-price gross gain; it is a counterfactual estimate, not an executed exit.",
            "A missing capture is reported as unmatched and is never silently filled with current strategy settings.",
        ],
    }


__all__ = ["build_linked_entry_outcome_analysis"]
