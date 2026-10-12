"""Compact, read-only diagnostics for Paper entry-lane signals.

This module describes values produced by the strategy. It must never create,
change, or approve a trading signal.
"""
from __future__ import annotations

from collections.abc import Mapping
from math import isfinite
from typing import Any


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if isfinite(number) else None


def _signal(value: Any) -> str:
    normalized = str(value or "HOLD").strip().upper()
    return normalized if normalized in {"BUY", "HOLD", "SELL"} else "UNKNOWN"


def _reasons(value: Any, *, limit: int = 10) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item)[:160] for item in value[:limit] if item is not None]


def _compact_entry_trace(trace: Any) -> dict[str, Any]:
    if not isinstance(trace, Mapping):
        return {}
    result: dict[str, Any] = {}
    for key in (
        "result",
        "execution",
        "execution_outcome",
        "brain_authority_rejection_reason",
        "finished_at",
    ):
        value = trace.get(key)
        if isinstance(value, (str, int, float, bool)) or value is None:
            if value is not None:
                result[key] = value

    pre_trade = trace.get("pre_trade")
    if isinstance(pre_trade, Mapping):
        result["pre_trade"] = {
            str(key): str(value)
            for key, value in pre_trade.items()
            if isinstance(value, (str, int, float, bool))
        }

    authority_by_mode = trace.get("brain_authority_by_mode")
    if isinstance(authority_by_mode, Mapping):
        compact_authority: dict[str, dict[str, Any]] = {}
        for mode in ("SCALP", "SWING"):
            record = authority_by_mode.get(mode)
            if not isinstance(record, Mapping):
                continue
            item: dict[str, Any] = {}
            if isinstance(record.get("allowed"), bool):
                item["allowed"] = record["allowed"]
            for key in ("decision_state", "brain_reason", "reason", "stage"):
                value = record.get(key)
                if isinstance(value, str) and value:
                    item[key] = value[:160]
            compact_authority[mode] = item
        if compact_authority:
            result["brain_authority_by_mode"] = compact_authority
    return result


def build_paper_entry_gate_summary(
    scores: Mapping[str, Any],
    *,
    scalp_threshold: float = 65,
    swing_threshold: float = 80,
    venue_mode: str = "UNKNOWN",
    entry_diagnostics: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a small view of actual lane scores, signals, and gate reasons."""
    traces = entry_diagnostics if isinstance(entry_diagnostics, Mapping) else {}
    rows: list[dict[str, Any]] = []

    source_scores = scores if isinstance(scores, Mapping) else {}
    for symbol, raw in source_scores.items():
        if not isinstance(raw, Mapping):
            continue

        normalized_symbol = str(symbol).upper()
        selected_score = _number(raw.get("score"))
        trade_mode = str(raw.get("trade_mode") or "NONE").strip().upper()
        scalp_score = _number(raw.get("scalp_score"))
        swing_score = _number(raw.get("swing_score"))
        if scalp_score is None and trade_mode == "SCALP":
            scalp_score = selected_score
        if swing_score is None and trade_mode == "SWING":
            swing_score = selected_score

        scalp_signal = _signal(
            raw.get("scalp_signal", raw.get("signal") if trade_mode == "SCALP" else "HOLD")
        )
        swing_signal = _signal(
            raw.get("swing_signal", raw.get("signal") if trade_mode == "SWING" else "HOLD")
        )
        gate_value = raw.get("scalp_gate")
        scalp_gate = gate_value if isinstance(gate_value, bool) else None
        scalp_reasons = _reasons(raw.get("scalp_gate_reasons"))
        if scalp_score is None:
            scalp_status = "SCORE_UNAVAILABLE"
        elif scalp_signal == "BUY":
            scalp_status = "SIGNAL_BUY"
        elif scalp_score < float(scalp_threshold):
            scalp_status = "BELOW_THRESHOLD"
        elif scalp_gate is False:
            scalp_status = "GATE_BLOCKED"
        elif scalp_gate is True:
            scalp_status = "GATE_PASSED_BUT_SIGNAL_HOLD"
        else:
            scalp_status = "THRESHOLD_MET_GATE_UNREPORTED"

        if swing_score is None:
            swing_status = "SCORE_UNAVAILABLE"
        elif swing_signal == "BUY":
            swing_status = "SIGNAL_BUY"
        elif swing_score < float(swing_threshold):
            swing_status = "BELOW_THRESHOLD"
        else:
            swing_status = "THRESHOLD_MET_SIGNAL_HOLD"

        row: dict[str, Any] = {
            "symbol": normalized_symbol,
            "score": selected_score,
            "trade_mode": trade_mode,
            "scalp_score": scalp_score,
            "scalp_signal": scalp_signal,
            "scalp_threshold_met": scalp_score is not None and scalp_score >= float(scalp_threshold),
            "scalp_gate": scalp_gate,
            "scalp_status": scalp_status,
            "scalp_gate_reasons": scalp_reasons,
            "scalp_confirmed_reversal": raw.get("scalp_confirmed_reversal"),
            "scalp_recovery_confirmation": raw.get("scalp_recovery_confirmation"),
            "scalp_structural_confirmation": raw.get("scalp_structural_confirmation"),
            "scalp_recovery_trigger_count": raw.get("scalp_recovery_trigger_count"),
            "swing_score": swing_score,
            "swing_signal": swing_signal,
            "swing_threshold_met": swing_score is not None and swing_score >= float(swing_threshold),
            "swing_status": swing_status,
        }

        # Include deeper trace details only for symbols whose current score has
        # an actual BUY signal. Traces for non-candidates can describe an older
        # scan and should not be presented as the current cycle's rejection.
        if scalp_signal == "BUY" or swing_signal == "BUY":
            trace = traces.get(normalized_symbol)
            compact_trace = _compact_entry_trace(trace)
            if compact_trace:
                row["entry_trace"] = compact_trace
        rows.append(row)

    rows.sort(
        key=lambda item: max(
            item["scalp_score"] if item["scalp_score"] is not None else -1.0,
            item["swing_score"] if item["swing_score"] is not None else -1.0,
        ),
        reverse=True,
    )

    scalp_at_threshold = [
        row for row in rows
        if row["scalp_score"] is not None and row["scalp_score"] >= float(scalp_threshold)
    ]
    swing_at_threshold = [
        row for row in rows
        if row["swing_score"] is not None and row["swing_score"] >= float(swing_threshold)
    ]
    scalp_buys = [row for row in rows if row["scalp_signal"] == "BUY"]
    swing_buys = [row for row in rows if row["swing_signal"] == "BUY"]
    buy_symbols = sorted({
        row["symbol"] for row in rows
        if row["scalp_signal"] == "BUY" or row["swing_signal"] == "BUY"
    })

    return {
        "available": True,
        "mode": "PAPER",
        "paper_only": True,
        "venue_mode": str(venue_mode or "UNKNOWN").upper(),
        "symbol_count": len(rows),
        "scalp_threshold": float(scalp_threshold),
        "swing_threshold": float(swing_threshold),
        "scalp_scores_at_or_above_threshold": len(scalp_at_threshold),
        "scalp_signals_buy": len(scalp_buys),
        "scalp_threshold_met_but_not_buy": sum(row["scalp_signal"] != "BUY" for row in scalp_at_threshold),
        "scalp_gate_blocked_at_threshold": sum(
            row["scalp_signal"] != "BUY" and row["scalp_gate"] is False
            for row in scalp_at_threshold
        ),
        "swing_scores_at_or_above_threshold": len(swing_at_threshold),
        "swing_signals_buy": len(swing_buys),
        "swing_threshold_met_but_not_buy": sum(row["swing_signal"] != "BUY" for row in swing_at_threshold),
        "buy_symbol_count": len(buy_symbols),
        "buy_symbols": buy_symbols,
        "top_symbols": rows,
    }
