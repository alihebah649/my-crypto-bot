"""Linked, read-only forensics for Paper entry captures and closed outcomes.

Joins MAIN outcomes by Entry-v2 capture_id and hosted labs by position_id.
It computes empirical execution economics; it never changes a trade decision.
"""
from __future__ import annotations

from collections import Counter, defaultdict
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


def _peak_gain_band(value: Any) -> str:
    """Bucket recorded peak gain in percentage points for exit-protection analysis."""
    peak = _number(value)
    if peak is None:
        return "UNKNOWN"
    if peak <= 0.0:
        return "NON_POSITIVE"
    if peak < 0.20:
        return "POSITIVE_UNDER_0_20"
    if peak < 0.40:
        return "0_20_TO_0_40"
    if peak < 0.60:
        return "0_40_TO_0_60"
    if peak < 1.00:
        return "0_60_TO_1_00"
    if peak < 2.00:
        return "1_00_TO_2_00"
    return "2_PLUS"


def _joined_row(
    venue: str,
    outcome: Mapping[str, Any],
    capture: Mapping[str, Any] | None,
) -> dict[str, Any]:
    # An exact capture remains the strongest source. When it is absent, the
    # closed outcome may still contain a frozen copy of entry-time fields.
    # Keep the provenance explicit rather than treating that fallback as a
    # recovered ENTRY_V2_CAPTURE row.
    capture = _mapping(capture)
    candidate, legacy, scenario, scenario_risk = _capture_parts(capture)
    outcome_v2 = _mapping(outcome.get("entry_v2"))
    entry_chain = _mapping(outcome.get("entry_decision_chain"))
    chain_v2 = _mapping(entry_chain.get("entry_v2"))
    chain_legacy = _mapping(entry_chain.get("legacy"))
    capture_v2 = _mapping(capture.get("v2_decision"))
    outcome_forensics = _mapping(outcome.get("entry_forensics"))
    outcome_regime = _mapping(outcome.get("regime"))
    outcome_strategy = _mapping(outcome.get("strategy"))
    chain_brain = _mapping(entry_chain.get("brain_authority"))
    chain_final = _mapping(entry_chain.get("final"))

    mode = str(
        outcome.get("trade_mode")
        or candidate.get("trade_mode")
        or scenario.get("trade_mode")
        or legacy.get("trade_mode")
        or entry_chain.get("trade_mode")
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
    if stop is None:
        # The normalized outcome persists the entry-time stop distance even
        # when its absolute stop price is unavailable.
        stop_percent = _number(outcome_forensics.get("stop_distance_percent"))
        entry_for_stop = _price(entry)
        if stop_percent is not None and stop_percent > 0 and entry_for_stop is not None:
            stop = entry_for_stop * (1.0 - stop_percent / 100.0)

    target = _price(
        scenario_risk.get("target_price")
        or outcome_v2.get("target_price")
        or candidate.get("target_price")
    )
    economics = _mapping(
        capture.get("entry_economics") or outcome.get("entry_economics")
    )
    risk = _mapping(scenario_risk)
    strategy = outcome_strategy
    atr = _first_number(
        legacy.get("atr"),
        strategy.get("atr"),
        candidate.get("atr"),
        outcome_forensics.get("atr"),
    )
    quantity = _first_number(outcome.get("quantity"))
    gross_pnl = _first_number(outcome.get("gross_pnl"))
    net_pnl = _first_number(outcome.get("realized_pnl"))
    fees = _first_number(outcome.get("fees"))
    exit_protection = _mapping(outcome.get("exit_protection"))
    protection_flag = exit_protection.get("paper_profit_protection")
    protection_triggered = (
        protection_flag if isinstance(protection_flag, bool) else None
    )
    protection_detail = _mapping(
        exit_protection.get("paper_profit_protection_detail")
    )
    shadow_trial = _mapping(exit_protection.get("net_floor_shadow_trial"))
    adaptive_shadow = _mapping(capture.get("adaptive_scalp_shadow"))
    neutral_low_score_shadow = _mapping(
        adaptive_shadow.get("neutral_low_score_experiment")
        or outcome_forensics.get("neutral_low_score_shadow")
    )
    maturity_shadow = _mapping(adaptive_shadow.get("maturity_experiment"))
    recovery_trigger = _mapping(scenario.get("trigger"))
    recovery_follow_through_shadow = _mapping(
        recovery_trigger.get("recovery_follow_through_shadow")
        or outcome_v2.get("recovery_follow_through_shadow")
    )
    shadow_status = str(shadow_trial.get("status") or "UNKNOWN").upper()
    shadow_triggered_value = shadow_trial.get("triggered")
    shadow_triggered = (
        shadow_triggered_value if isinstance(shadow_triggered_value, bool) else None
    )
    shadow_net_pnl = _first_number(
        shadow_trial.get("net_pnl_estimate_after_fees")
    )
    shadow_exit_price = _price(shadow_trial.get("exit_price"))
    shadow_delta_vs_actual = (
        shadow_net_pnl - net_pnl
        if shadow_net_pnl is not None and net_pnl is not None
        and shadow_triggered is True
        else None
    )
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
        chain_legacy.get("score"),
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
    risk_notional = (
        stop_distance * quantity
        if stop_distance is not None and quantity is not None
        and stop_distance > 0 and quantity > 0
        else None
    )
    realized_r = (
        net_pnl / risk_notional
        if net_pnl is not None and risk_notional is not None
        else None
    )
    fee_r_multiple = (
        fees / risk_notional
        if fees is not None and risk_notional is not None
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
    raw_regime = (
        capture.get("market_regime")
        or candidate.get("market_regime")
        or outcome_regime.get("market")
        or _mapping(scenario.get("market")).get("regime")
        or strategy.get("market_regime")
    )
    regime_source = (
        "ENTRY_CAPTURE"
        if capture.get("market_regime") or candidate.get("market_regime")
        else "OUTCOME_REGIME"
        if outcome_regime.get("market")
        else "ENTRY_SCENARIO"
        if _mapping(scenario.get("market")).get("regime")
        else "STRATEGY_SNAPSHOT"
        if strategy.get("market_regime")
        else "UNKNOWN"
    )
    market_regime = str(raw_regime or "UNKNOWN").upper()
    symbol_regime = str(
        outcome_regime.get("symbol")
        or strategy.get("symbol_regime")
        or _mapping(scenario.get("market")).get("symbol_regime")
        or "UNKNOWN"
    ).upper()
    mtf_bias = str(
        outcome_forensics.get("mtf_bias")
        or strategy.get("mtf_bias")
        or outcome_regime.get("mtf_bias")
        or "UNKNOWN"
    ).upper()
    mtf_net = _first_number(
        outcome_forensics.get("mtf_net"),
        strategy.get("mtf_net"),
        outcome_regime.get("mtf_net"),
    )
    rsi5m = _first_number(
        legacy.get("rsi5m"),
        strategy.get("rsi5m"),
        outcome_forensics.get("rsi5m"),
    )
    volume_ratio_5m = _first_number(
        legacy.get("volume_ratio_5m"),
        strategy.get("volume_ratio_5m"),
        outcome_forensics.get("volume_ratio_5m"),
    )
    mtf_net_band = (
        "UNKNOWN" if mtf_net is None else
        "BELOW_-20" if mtf_net <= -20 else
        "-20_TO_-10" if mtf_net < -10 else
        "-10_TO_0" if mtf_net < 0 else
        "0_TO_10" if mtf_net < 10 else
        "10_TO_20" if mtf_net < 20 else
        "20_PLUS"
    )
    volume_band = (
        "UNKNOWN" if volume_ratio_5m is None else
        "BELOW_1_0" if volume_ratio_5m < 1.0 else
        "1_00_TO_1_49" if volume_ratio_5m < 1.5 else
        "1_50_TO_1_99" if volume_ratio_5m < 2.0 else
        "2_PLUS"
    )
    rsi5m_band = (
        "UNKNOWN" if rsi5m is None else
        "30_OR_BELOW" if rsi5m <= 30 else
        "30_TO_40" if rsi5m < 40 else
        "40_TO_49" if rsi5m < 49 else
        "49_TO_60" if rsi5m < 60 else
        "60_PLUS"
    )
    outcome_has_entry_context = any(
        value is not None and value != ""
        for value in (
            outcome.get("entry_stop_loss"),
            outcome.get("signal_entry_price"),
            outcome_v2.get("decision"),
            outcome_v2.get("approved"),
            outcome_v2.get("failed_gate"),
            outcome_v2.get("reward_risk"),
            outcome_v2.get("target_price"),
            economics.get("reward_risk"),
            economics.get("risk_percent"),
            economics.get("net_reward_percent"),
            strategy.get("score"),
            strategy.get("scalp_score"),
            strategy.get("swing_score"),
            strategy.get("rsi5m"),
            strategy.get("volume_ratio_5m"),
            outcome_forensics.get("mtf_bias"),
            outcome_forensics.get("mtf_net"),
            outcome_regime.get("market"),
            chain_legacy.get("score"),
            chain_legacy.get("signal"),
            chain_brain.get("allowed"),
            chain_brain.get("reason"),
            chain_final.get("failed_gate"),
        )
    )
    capture_matched = bool(capture)
    decision_evidence_source = (
        "ENTRY_CAPTURE"
        if capture_matched
        else "OUTCOME_EMBEDDED_ENTRY_CONTEXT"
        if outcome_has_entry_context
        else "OUTCOME_ONLY"
    )
    score_band = (
        "UNKNOWN" if score is None else
        "BELOW_65" if score < 65 else
        "65_69" if score < 70 else
        "70_74" if score < 75 else
        "75_79" if score < 80 else
        "80_84" if score < 85 else
        "85_89" if score < 90 else
        "90_PLUS"
    )
    peak_gain_band = _peak_gain_band(max_profit_percent)

    return {
        "venue": str(venue).upper(),
        "position_id": str(outcome.get("position_id") or "").strip(),
        "capture_id": str(capture.get("capture_id") or _capture_id_from_outcome(outcome) or "").strip() or None,
        "capture_matched": capture_matched,
        "decision_evidence_source": decision_evidence_source,
        "entry_context_available": bool(capture_matched or outcome_has_entry_context),
        "symbol": symbol,
        "trade_mode": mode,
        "score": score,
        "score_band": score_band,
        "market_regime_source": regime_source,
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
        "fees_as_r_multiple": fee_r_multiple,
        "highest_price": highest,
        "max_profit_percent": max_profit_percent,
        "net_mfe": net_mfe,
        "mfe_source": mfe_source,
        "peak_gain_percent": max_profit_percent,
        "peak_gain_band": peak_gain_band,
        "paper_profit_protection_triggered": protection_triggered,
        "paper_profit_protection_detail": (
            {
                "current_gain_percent": _number(protection_detail.get("current_gain_percent")),
                "peak_gain_percent": _number(protection_detail.get("peak_gain_percent")),
                "retrace_percent": _number(protection_detail.get("retrace_percent")),
                "min_gain_percent": _number(protection_detail.get("min_gain_percent")),
                "min_retrace_percent": _number(protection_detail.get("min_retrace_percent")),
            }
            if protection_detail else None
        ),
        "profit_protection_shadow_status": shadow_status,
        "profit_protection_shadow_triggered": shadow_triggered,
        "profit_protection_shadow_net_pnl_after_fees": shadow_net_pnl,
        "profit_protection_shadow_delta_vs_actual": shadow_delta_vs_actual,
        "profit_protection_shadow_exit_price": shadow_exit_price,
        "profit_protection_shadow_detail": (
            {
                "current_gain_percent": _number(shadow_trial.get("current_gain_percent")),
                "peak_gain_percent": _number(shadow_trial.get("peak_gain_percent")),
                "retrace_percent": _number(shadow_trial.get("retrace_percent")),
                "gross_pnl_estimate": _number(shadow_trial.get("gross_pnl_estimate")),
                "entry_fee_paid": _number(shadow_trial.get("entry_fee_paid")),
                "estimated_exit_fee": _number(shadow_trial.get("estimated_exit_fee")),
                "net_pnl_estimate_after_fees": shadow_net_pnl,
            }
            if shadow_trial else None
        ),
        "classifier_shadow": {
            "adaptive_scalp": {
                "classification": str(adaptive_shadow.get("classification") or "UNAVAILABLE").upper(),
                "advisory_action": str(adaptive_shadow.get("advisory_action") or "NO_ACTION").upper(),
                "reasons": list(adaptive_shadow.get("reasons", []) or []),
            },
            "neutral_low_score": {
                "would_be_action": str(neutral_low_score_shadow.get("would_be_action") or "UNAVAILABLE").upper(),
                "gate_pass": neutral_low_score_shadow.get("gate_pass"),
                "mtf_bias": str(neutral_low_score_shadow.get("mtf_bias") or strategy.get("mtf_bias") or "UNKNOWN").upper(),
                "scalp_score": _number(neutral_low_score_shadow.get("scalp_score") or strategy.get("scalp_score")),
                "reasons": list(neutral_low_score_shadow.get("reasons", []) or []),
                "evidence_source": "ENTRY_CAPTURE" if adaptive_shadow.get("neutral_low_score_experiment") else ("OUTCOME_EMBEDDED_ENTRY_CONTEXT" if outcome_forensics.get("neutral_low_score_shadow") else "UNAVAILABLE"),
            },
            "maturity": {
                "would_be_action": str(maturity_shadow.get("would_be_action") or "UNAVAILABLE").upper(),
                "gate_pass": maturity_shadow.get("gate_pass"),
                "reasons": list(maturity_shadow.get("reasons", []) or []),
            },
            "recovery_follow_through": {
                "would_be_action": str(recovery_follow_through_shadow.get("would_be_action") or "UNAVAILABLE").upper(),
                "reasons": list(recovery_follow_through_shadow.get("reasons", []) or []),
                "evidence_source": "ENTRY_CAPTURE" if recovery_trigger.get("recovery_follow_through_shadow") else ("OUTCOME_EMBEDDED_ENTRY_CONTEXT" if outcome_v2.get("recovery_follow_through_shadow") else "UNAVAILABLE"),
                "observation": dict(recovery_follow_through_shadow),
            },
        },
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
        "market_regime": market_regime,
        "symbol_regime": symbol_regime,
        "mtf_bias": mtf_bias,
        "mtf_net": mtf_net,
        "mtf_net_band": mtf_net_band,
        "rsi5m": rsi5m,
        "rsi5m_band": rsi5m_band,
        "volume_ratio_5m": volume_ratio_5m,
        "volume_band": volume_band,
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
    paired_rr_rows = [
        row for row in rows
        if _number(row.get("expected_rr")) is not None
        and _number(row.get("expected_net_rr_after_fees")) is not None
    ]
    paired_gross_rr = [_number(row.get("expected_rr")) for row in paired_rr_rows]
    paired_net_rr = [
        _number(row.get("expected_net_rr_after_fees")) for row in paired_rr_rows
    ]
    valid_realized_r = [_number(row.get("realized_r_multiple_net")) for row in rows]
    valid_fee_r = [_number(row.get("fees_as_r_multiple")) for row in rows]
    valid_stop_atr = [_number(row.get("stop_atr_multiple")) for row in rows]
    valid_mfe = [_number(row.get("net_mfe")) for row in rows]
    losing_rows = [row for row in rows if (_number(row.get("net_pnl")) or 0.0) < 0]
    losing_with_positive_mfe = [
        row for row in losing_rows
        if _number(row.get("net_mfe")) is not None and float(row["net_mfe"]) > 0
    ]
    target_rows = [row for row in rows if row.get("target_reached") is not None]
    target_hits = [row for row in target_rows if row.get("target_reached") is True]
    protection_rows = [
        row for row in rows
        if isinstance(row.get("paper_profit_protection_triggered"), bool)
    ]
    protection_triggered_rows = [
        row for row in protection_rows
        if row.get("paper_profit_protection_triggered") is True
    ]
    peak_gain_values = [_number(row.get("peak_gain_percent")) for row in rows]
    shadow_observed_rows = [
        row for row in rows
        if str(row.get("profit_protection_shadow_status") or "UNKNOWN").upper()
        in {"OBSERVING", "TRIGGERED"}
    ]
    shadow_triggered_rows = [
        row for row in rows
        if str(row.get("profit_protection_shadow_status") or "UNKNOWN").upper()
        == "TRIGGERED"
    ]
    shadow_estimates = [
        _number(row.get("profit_protection_shadow_net_pnl_after_fees"))
        for row in shadow_triggered_rows
    ]
    shadow_actuals = [_number(row.get("net_pnl")) for row in shadow_triggered_rows]
    shadow_deltas = [
        _number(row.get("profit_protection_shadow_delta_vs_actual"))
        for row in shadow_triggered_rows
    ]
    shadow_skipped_partial = sum(
        str(row.get("profit_protection_shadow_status") or "").upper()
        == "SKIPPED_PARTIAL_EXIT"
        for row in rows
    )

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
        "expected_rr_sample_count": sum(value is not None for value in valid_rr),
        "average_expected_net_rr_after_fees": mean(valid_net_rr),
        "expected_net_rr_sample_count": sum(value is not None for value in valid_net_rr),
        "paired_expected_rr_sample_count": len(paired_rr_rows),
        "paired_average_expected_rr": mean(paired_gross_rr),
        "paired_average_expected_net_rr_after_fees": mean(paired_net_rr),
        "average_realized_r_multiple_net": mean(valid_realized_r),
        "average_fees_as_r_multiple": mean(valid_fee_r),
        "fees_as_r_sample_count": sum(value is not None for value in valid_fee_r),
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
        "peak_gain_percent_observed_trades": sum(value is not None for value in peak_gain_values),
        "average_peak_gain_percent": mean(peak_gain_values),
        "paper_profit_protection_observed_trades": len(protection_rows),
        "paper_profit_protection_triggered_trades": len(protection_triggered_rows),
        "paper_profit_protection_trigger_rate_percent": (
            round(len(protection_triggered_rows) / len(protection_rows) * 100.0, 2)
            if protection_rows else None
        ),
        "net_floor_shadow_observed_trades": len(shadow_observed_rows),
        "net_floor_shadow_triggered_trades": len(shadow_triggered_rows),
        "net_floor_shadow_trigger_rate_percent": (
            round(len(shadow_triggered_rows) / len(shadow_observed_rows) * 100.0, 2)
            if shadow_observed_rows else None
        ),
        "net_floor_shadow_skipped_partial_exit_trades": shadow_skipped_partial,
        "net_floor_shadow_estimated_net_pnl_on_triggered_trades": round(
            sum(value or 0.0 for value in shadow_estimates), 6
        ),
        "actual_net_pnl_on_shadow_triggered_trades": round(
            sum(value or 0.0 for value in shadow_actuals), 6
        ),
        "net_floor_shadow_delta_vs_actual_on_triggered_trades": round(
            sum(value or 0.0 for value in shadow_deltas), 6
        ),
        "average_net_floor_shadow_delta_vs_actual": mean(shadow_deltas),
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


def _group_by_two_keys(
    rows: list[Mapping[str, Any]],
    first_key: str,
    second_key: str,
) -> dict[str, dict[str, Any]]:
    buckets: dict[str, dict[str, list[Mapping[str, Any]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for row in rows:
        first = str(row.get(first_key) or "UNKNOWN").upper()
        second_value = row.get(second_key)
        second = "UNKNOWN" if second_value is None or second_value == "" else str(second_value).upper()
        buckets[first][second].append(row)
    return {
        first: {
            second: _aggregate(buckets[first][second])
            for second in sorted(buckets[first])
        }
        for first in sorted(buckets)
    }


def _rule_metrics(samples: list[Mapping[str, Any]]) -> dict[str, Any]:
    values = [_number(row.get("net_pnl_after_fees")) for row in samples]
    clean = [value for value in values if value is not None]
    wins = sum(1 for value in clean if value > 0)
    losses = sum(1 for value in clean if value < 0)
    fees = [_number(row.get("fees")) for row in samples]
    known_fees = [value for value in fees if value is not None]
    return {
        "completed": len(samples), "wins": wins, "losses": losses,
        "flat": len(clean) - wins - losses,
        "net_pnl_after_fees": round(sum(clean), 6) if clean else 0.0,
        "fees_recorded": round(sum(known_fees), 6) if known_fees else 0.0,
        "average_net_pnl_after_fees": round(sum(clean) / len(clean), 6) if clean else None,
    }


def _classification_sample(row: Mapping[str, Any], rule: str, label: str, action: str) -> dict[str, Any]:
    observation = _mapping(_mapping(row.get("classifier_shadow")).get(rule))
    return {
        "venue": row.get("venue"), "trade_mode": row.get("trade_mode"),
        "position_id": row.get("position_id"), "capture_id": row.get("capture_id"),
        "capture_matched": bool(row.get("capture_matched")),
        "evidence_source": observation.get("evidence_source") or ("ENTRY_CAPTURE" if row.get("capture_matched") else row.get("decision_evidence_source")),
        "symbol": row.get("symbol"), "classification": label,
        "would_be_action": action, "reasons": list(observation.get("reasons", []) or []),
        "close_reason": row.get("close_reason"),
        # realized_pnl has already had the recorded fees deducted by Paper execution.
        "net_pnl_after_fees": row.get("net_pnl"), "fees": row.get("fees"),
    }


def _classification_shadow_rule_progress(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Link each captured classification to one unique closed Paper outcome."""
    definitions = {
        "adaptive_scalp": {"field": "adaptive_scalp", "label_field": "classification", "action_field": "advisory_action", "requires_capture": True,
            "description": "Adaptive Scalp classification on captured SCALP entries"},
        "neutral_low_score": {"field": "neutral_low_score", "label_field": "would_be_action", "action_field": "would_be_action", "requires_capture": False,
            "description": "Only WOULD_BLOCK rows satisfying score 65-69 and neutral MTF count; WOULD_ALLOW rows are controls"},
        "maturity": {"field": "maturity", "label_field": "would_be_action", "action_field": "would_be_action", "requires_capture": True,
            "description": "Maturity experiment based on the captured recovery-trigger count"},
        "recovery_follow_through": {"field": "recovery_follow_through", "label_field": "would_be_action", "action_field": "would_be_action", "requires_capture": False,
            "description": "Recovery Follow-Through result from the two closed 5m candles"},
    }
    result: dict[str, Any] = {}
    for rule, definition in definitions.items():
        by_mode: dict[str, Any] = {}
        for mode in ("SCALP", "SWING", "UNKNOWN"):
            cohort = [row for row in rows if str(row.get("trade_mode") or "UNKNOWN").upper() == mode]
            exclusions: Counter[str] = Counter()
            seen_positions: set[str] = set()
            samples: list[dict[str, Any]] = []
            controls: list[dict[str, Any]] = []
            grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for row in cohort:
                position_id = str(row.get("position_id") or "").strip()
                if not position_id:
                    exclusions["MISSING_POSITION_ID"] += 1
                    continue
                if position_id in seen_positions:
                    exclusions["DUPLICATE_POSITION_ID"] += 1
                    continue
                seen_positions.add(position_id)
                if mode != "SCALP":
                    exclusions["MODE_NOT_APPLICABLE_SCALP_ONLY_RULE"] += 1
                    continue
                if definition["requires_capture"] and not row.get("capture_matched"):
                    exclusions["ENTRY_CAPTURE_NOT_MATCHED"] += 1
                    continue
                observation = _mapping(_mapping(row.get("classifier_shadow")).get(definition["field"]))
                if not observation:
                    exclusions["CLASSIFIER_OBSERVATION_UNAVAILABLE"] += 1
                    continue
                action = str(observation.get(definition["action_field"]) or "UNAVAILABLE").upper()
                if rule == "neutral_low_score" and action == "WOULD_ALLOW":
                    if _number(row.get("net_pnl")) is None or _number(row.get("fees")) is None:
                        exclusions["CONTROL_OUTCOME_OR_FEES_UNAVAILABLE"] += 1
                        continue
                    controls.append(_classification_sample(row, rule, "WOULD_ALLOW_CONTROL", action))
                    exclusions["CONTROL_WOULD_ALLOW_NOT_RULE_APPLICABLE"] += 1
                    continue
                if action not in {"WOULD_ALLOW", "WOULD_BLOCK"} and rule != "adaptive_scalp":
                    exclusions[f"INVALID_ACTION_{action}"] += 1
                    continue
                if rule == "adaptive_scalp":
                    label = str(observation.get(definition["label_field"]) or "UNAVAILABLE").upper()
                    if label in {"", "UNKNOWN", "UNAVAILABLE", "NOT_APPLICABLE"}:
                        exclusions["ADAPTIVE_CLASSIFICATION_UNAVAILABLE"] += 1
                        continue
                    action = str(observation.get("advisory_action") or "NO_ACTION").upper()
                else:
                    label = action
                if _number(row.get("net_pnl")) is None:
                    exclusions["NET_PNL_UNAVAILABLE"] += 1
                    continue
                if _number(row.get("fees")) is None:
                    exclusions["FEES_UNAVAILABLE"] += 1
                    continue
                sample = _classification_sample(row, rule, label, action)
                samples.append(sample)
                grouped[label].append(sample)
            by_mode[mode] = {
                "target_samples": 50, "completed": len(samples),
                "remaining_to_50": max(0, 50 - len(samples)),
                "exclusions": dict(sorted(exclusions.items())),
                "by_classification": {label: _rule_metrics(group) for label, group in sorted(grouped.items())},
                "controls_not_counted": {
                    "completed": len(controls),
                    "by_action": {"WOULD_ALLOW": _rule_metrics(controls)} if controls else {},
                    "samples": controls[:100],
                },
                "samples": samples[:250],
                "sample_records_truncated": max(0, len(samples) - 250),
                "pnl_basis": "PAPER_OUTCOME.realized_pnl is already net of recorded fees; fees are shown separately and not deducted again",
            }
        result[rule] = {"description": definition["description"], "target_samples_per_venue_and_mode": 50, "by_trade_mode": by_mode}
    return result


def _net_floor_sample_progress(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Count closed Paper positions with a valid persisted Net-Floor observation."""
    by_mode: dict[str, Any] = {}
    for mode in ("SCALP", "SWING", "UNKNOWN"):
        cohort = [row for row in rows if str(row.get("trade_mode") or "UNKNOWN").upper() == mode]
        exclusions: Counter[str] = Counter()
        seen: set[str] = set()
        samples: list[dict[str, Any]] = []
        for row in cohort:
            position_id = str(row.get("position_id") or "").strip()
            if not position_id:
                exclusions["MISSING_POSITION_ID"] += 1
                continue
            if position_id in seen:
                exclusions["DUPLICATE_POSITION_ID"] += 1
                continue
            seen.add(position_id)
            status = str(row.get("profit_protection_shadow_status") or "UNKNOWN").upper()
            if status == "SKIPPED_PARTIAL_EXIT":
                exclusions["SKIPPED_PARTIAL_EXIT"] += 1
                continue
            if status not in {"OBSERVING", "TRIGGERED"}:
                exclusions[f"NO_VALID_NET_FLOOR_OBSERVATION_{status}"] += 1
                continue
            if _number(row.get("net_pnl")) is None:
                exclusions["ACTUAL_NET_PNL_UNAVAILABLE"] += 1
                continue
            if _number(row.get("fees")) is None:
                exclusions["RECORDED_FEES_UNAVAILABLE"] += 1
                continue
            samples.append({
                "position_id": position_id, "symbol": row.get("symbol"), "trade_mode": mode,
                "status": status, "net_pnl_after_fees": row.get("net_pnl"), "fees": row.get("fees"),
                "shadow_net_pnl_after_fees": row.get("profit_protection_shadow_net_pnl_after_fees"),
            })
        metrics = _rule_metrics(samples)
        by_mode[mode] = {
            "target_samples": 50, "completed": metrics["completed"],
            "remaining_to_50": max(0, 50 - metrics["completed"]),
            "wins": metrics["wins"], "losses": metrics["losses"],
            "net_pnl_after_fees": metrics["net_pnl_after_fees"], "fees_recorded": metrics["fees_recorded"],
            "exclusions": dict(sorted(exclusions.items())),
            "status_counts": dict(Counter(sample["status"] for sample in samples)),
        }
    return {"target_samples_per_venue_and_mode": 50, "by_trade_mode": by_mode}


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

    # Aggregate every closed outcome. Exact capture matches and outcome-only
    # fallbacks are tracked separately so wider analysis coverage is never
    # misreported as recovered capture linkage.
    joined: list[dict[str, Any]] = []
    unmatched_outcomes: list[Mapping[str, Any]] = []
    matched_capture_ids: set[str] = set()
    matched_position_keys: set[str] = set()
    capture_matched_count = 0
    outcome_context_fallback_count = 0
    unmatched_without_entry_context_count = 0

    for outcome in outcome_rows:
        position_id = str(outcome.get("position_id") or "").strip()
        capture_id = _capture_id_from_outcome(outcome)
        capture = by_id.get(capture_id) if capture_id else None
        if capture is None and position_id:
            capture = by_position.get(position_id)
        if capture is None:
            unmatched_outcomes.append(outcome)
            row = _joined_row(venue_name, outcome, {})
            if row.get("entry_context_available"):
                outcome_context_fallback_count += 1
            else:
                unmatched_without_entry_context_count += 1
        else:
            row = _joined_row(venue_name, outcome, capture)
            capture_matched_count += 1
            matched_capture_id = str(capture.get("capture_id") or "").strip()
            if matched_capture_id:
                matched_capture_ids.add(matched_capture_id)
            if position_id:
                matched_position_keys.add(position_id)
        joined.append(row)

    decision_evidence_covered = sum(
        bool(row.get("entry_context_available")) for row in joined
    )
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
            "position_id", "capture_id", "capture_matched",
            "decision_evidence_source", "entry_context_available",
            "symbol", "trade_mode", "score", "net_pnl", "fees",
            "expected_rr", "expected_net_rr_after_fees",
            "realized_r_multiple_net", "stop_atr_multiple",
            "net_mfe", "peak_gain_percent", "peak_gain_band",
            "paper_profit_protection_triggered", "paper_profit_protection_detail",
            "profit_protection_shadow_status", "profit_protection_shadow_triggered",
            "profit_protection_shadow_net_pnl_after_fees",
            "profit_protection_shadow_delta_vs_actual", "profit_protection_shadow_exit_price",
            "profit_protection_shadow_detail",
            "target_reached", "close_reason",
            "entry_v2_approved_shadow", "entry_v2_failed_gate_shadow",
            "market_regime", "market_regime_source", "symbol_regime",
            "mtf_bias", "mtf_net", "mtf_net_band",
            "rsi5m", "rsi5m_band", "volume_ratio_5m", "volume_band",
        )
        return {key: row.get(key) for key in fields}

    return {
        "schema_version": 2,
        "venue": venue_name,
        "coverage": {
            "outcome_records_read": len(outcome_rows),
            "entry_captures_read": len(capture_rows),
            "matched_closed_trades": capture_matched_count,
            "unmatched_outcomes": len(unmatched_outcomes),
            "unmatched_entry_captures": unmatched_captures,
            "matched_percent_of_outcomes": (
                round(capture_matched_count / len(outcome_rows) * 100.0, 2)
                if outcome_rows else None
            ),
            "outcome_context_fallback_trades": outcome_context_fallback_count,
            "unmatched_outcomes_without_entry_context": unmatched_without_entry_context_count,
            "analyzed_closed_trades": len(joined),
            "analyzed_percent_of_outcomes": (
                round(len(joined) / len(outcome_rows) * 100.0, 2)
                if outcome_rows else None
            ),
            "decision_evidence_covered_trades": decision_evidence_covered,
            "decision_evidence_coverage_percent": (
                round(decision_evidence_covered / len(outcome_rows) * 100.0, 2)
                if outcome_rows else None
            ),
        },
        "overall": _aggregate(joined),
        "classification_shadow_rules": _classification_shadow_rule_progress(joined),
        "net_floor_shadow_progress": _net_floor_sample_progress(joined),
        "by_trade_mode": _group(joined, "trade_mode"),
        "by_trade_mode_and_failed_gate": _group_by_two_keys(
            joined, "trade_mode", "entry_v2_failed_gate_shadow"
        ),
        "by_trade_mode_and_score_band": _group_by_two_keys(
            joined, "trade_mode", "score_band"
        ),
        "by_trade_mode_and_market_regime": _group_by_two_keys(
            joined, "trade_mode", "market_regime"
        ),
        "by_trade_mode_and_symbol_regime": _group_by_two_keys(
            joined, "trade_mode", "symbol_regime"
        ),
        "by_trade_mode_and_mtf_bias": _group_by_two_keys(
            joined, "trade_mode", "mtf_bias"
        ),
        "by_trade_mode_and_mtf_net_band": _group_by_two_keys(
            joined, "trade_mode", "mtf_net_band"
        ),
        "by_trade_mode_and_volume_band": _group_by_two_keys(
            joined, "trade_mode", "volume_band"
        ),
        "by_trade_mode_and_rsi5m_band": _group_by_two_keys(
            joined, "trade_mode", "rsi5m_band"
        ),
        "by_trade_mode_and_decision_evidence_source": _group_by_two_keys(
            joined, "trade_mode", "decision_evidence_source"
        ),
        "by_trade_mode_and_peak_gain_band": _group_by_two_keys(
            joined, "trade_mode", "peak_gain_band"
        ),
        "by_trade_mode_and_paper_profit_protection": _group_by_two_keys(
            joined, "trade_mode", "paper_profit_protection_triggered"
        ),
        "by_trade_mode_and_profit_protection_shadow_status": _group_by_two_keys(
            joined, "trade_mode", "profit_protection_shadow_status"
        ),
        "by_close_reason": _group(joined, "close_reason"),
        "by_paper_profit_protection_triggered": _group(
            joined, "paper_profit_protection_triggered"
        ),
        "by_entry_v2_shadow_approval": _group(joined, "entry_v2_approved_shadow"),
        "by_entry_v2_shadow_failed_gate": _group(joined, "entry_v2_failed_gate_shadow"),
        "by_market_regime": _group(joined, "market_regime"),
        "by_market_regime_source": _group(joined, "market_regime_source"),
        "losers_with_positive_net_favorable_excursion": [
            public_sample(row) for row in losing_positive_mfe[:10]
        ],
        "worst_trades": [public_sample(row) for row in worst],
        "best_trades": [public_sample(row) for row in best],
        "limitations": [
            "Only closed outcomes in the requested time window are analyzed.",
            "A target hit is inferred from the recorded highest price; it is unavailable when that price was not persisted.",
            "Net favorable excursion subtracts the trade's recorded total fees from the peak-price gross gain; it is a counterfactual estimate, not an executed exit.",
            "Peak-gain bands use the captured maximum favorable percentage; they do not reconstruct the order of intratrade price ticks.",
            "Profit-protection activation is read from the persisted exit_protection flag; historical rows without that flag remain unknown.",
            "Net-floor shadow exits are counterfactual Paper-only observations at the first qualifying fresh mark; they do not execute an exit or model later slippage.",
            "Shadow-versus-actual PnL deltas are only computed for completed trades where the shadow trigger was persisted; partial-exit trades are excluded.",
            "A missing capture remains unmatched for capture-linkage coverage; aggregate analysis may use entry-time fields already embedded in that same closed outcome, with explicit OUTCOME_EMBEDDED_ENTRY_CONTEXT provenance.",
            "Market-regime, symbol-regime, MTF bias/net, RSI and volume are reported as separate dimensions; MTF fields are not inferred into an overall market-regime label.",
        ],
    }


__all__ = ["build_linked_entry_outcome_analysis"]
