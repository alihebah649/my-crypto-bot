"""Compact per-cycle signal funnel telemetry for Paper Trading.

This module summarizes strategy outputs only. It never changes, creates, or
approves a signal and is safe to use as read-only logging instrumentation.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from typing import Any

from .paper_entry_gate_summary import build_paper_entry_gate_summary


def build_paper_signal_cycle_summary(
    scores: Mapping[str, Any],
    *,
    scalp_threshold: float = 65,
    swing_threshold: float = 80,
    venue_mode: str = "UNKNOWN",
) -> dict[str, Any]:
    """Summarize lane scores, actual BUY signals, and reasons a threshold was not enough."""
    base = build_paper_entry_gate_summary(
        scores,
        scalp_threshold=scalp_threshold,
        swing_threshold=swing_threshold,
        venue_mode=venue_mode,
    )
    rows = base.get("top_symbols", [])
    rows = rows if isinstance(rows, list) else []

    scalp_status_counts = Counter(str(row.get("scalp_status") or "UNKNOWN") for row in rows)
    swing_status_counts = Counter(str(row.get("swing_status") or "UNKNOWN") for row in rows)
    scalp_block_reasons: Counter[str] = Counter()
    scalp_reasons_all_symbols: Counter[str] = Counter()
    threshold_candidates: list[dict[str, Any]] = []
    pre_calibration_candidates: list[dict[str, Any]] = []

    for row in rows:
        scalp_score = row.get("scalp_score")
        swing_score = row.get("swing_score")
        scalp_met = bool(row.get("scalp_threshold_met"))
        swing_met = bool(row.get("swing_threshold_met"))
        scalp_buy = str(row.get("scalp_signal") or "HOLD").upper() == "BUY"
        swing_buy = str(row.get("swing_signal") or "HOLD").upper() == "BUY"
        pre_cal_score = row.get("scalp_pre_calibration_score")
        pre_cal_met = bool(row.get("scalp_pre_calibration_threshold_met"))
        pre_cal_buy = str(row.get("scalp_pre_calibration_signal") or "HOLD").upper() == "BUY"
        reasons = row.get("scalp_gate_reasons")
        if isinstance(reasons, (list, tuple)):
            scalp_reasons_all_symbols.update(
                str(reason)[:120] for reason in reasons if reason
            )
            if scalp_met and not scalp_buy:
                scalp_block_reasons.update(
                    str(reason)[:120] for reason in reasons if reason
                )

        if pre_cal_met or pre_cal_buy or scalp_met or swing_met or scalp_buy or swing_buy:
            pre_calibration_candidates.append({
                "symbol": str(row.get("symbol") or "").upper(),
                "current_scalp_score": scalp_score,
                "current_scalp_signal": str(row.get("scalp_signal") or "HOLD").upper(),
                "current_scalp_status": str(row.get("scalp_status") or "UNKNOWN"),
                "pre_calibration_score": pre_cal_score,
                "pre_calibration_signal": str(row.get("scalp_pre_calibration_signal") or "HOLD").upper(),
                "pre_calibration_gate": row.get("scalp_pre_calibration_gate"),
                "current_gate_reasons": list(row.get("scalp_gate_reasons") or [])[:6],
                "scalp_score_raw": row.get("scalp_score_raw"),
                "reversion_family_points": row.get("scalp_reversion_family_points"),
                "rsi5m": row.get("scalp_rsi5m"),
                "volume_ratio_5m": row.get("scalp_volume_ratio_5m"),
                "pattern": row.get("scalp_pattern"),
                "pattern_confirmed": row.get("scalp_pattern_confirmed"),
                "recovery_confirmation": row.get("scalp_recovery_confirmation"),
                "structural_confirmation": row.get("scalp_structural_confirmation"),
                "mtf_bias": row.get("mtf_bias"),
                "mtf_net": row.get("mtf_net"),
            })

        if scalp_met or swing_met or scalp_buy or swing_buy:
            threshold_candidates.append({
                "symbol": str(row.get("symbol") or "").upper(),
                "scalp_score": scalp_score,
                "scalp_signal": str(row.get("scalp_signal") or "HOLD").upper(),
                "scalp_status": str(row.get("scalp_status") or "UNKNOWN"),
                "scalp_gate": row.get("scalp_gate"),
                "scalp_gate_reasons": list(row.get("scalp_gate_reasons") or [])[:6],
                "swing_score": swing_score,
                "swing_signal": str(row.get("swing_signal") or "HOLD").upper(),
                "swing_status": str(row.get("swing_status") or "UNKNOWN"),
            })

    top_scores = [
        {
            "symbol": str(row.get("symbol") or "").upper(),
            "score": row.get("score"),
            "trade_mode": str(row.get("trade_mode") or "NONE").upper(),
            "scalp_score": row.get("scalp_score"),
            "scalp_signal": str(row.get("scalp_signal") or "HOLD").upper(),
            "scalp_status": str(row.get("scalp_status") or "UNKNOWN"),
            "scalp_pre_calibration_score": row.get("scalp_pre_calibration_score"),
            "scalp_pre_calibration_signal": str(row.get("scalp_pre_calibration_signal") or "HOLD").upper(),
            "scalp_score_raw": row.get("scalp_score_raw"),
            "scalp_reversion_family_points": row.get("scalp_reversion_family_points"),
            "scalp_rsi5m": row.get("scalp_rsi5m"),
            "scalp_volume_ratio_5m": row.get("scalp_volume_ratio_5m"),
            "scalp_pattern": row.get("scalp_pattern"),
            "scalp_pattern_confirmed": row.get("scalp_pattern_confirmed"),
            "scalp_recovery_confirmation": row.get("scalp_recovery_confirmation"),
            "scalp_structural_confirmation": row.get("scalp_structural_confirmation"),
            "mtf_bias": row.get("mtf_bias"),
            "mtf_net": row.get("mtf_net"),
            "scalp_gate_reasons": list(row.get("scalp_gate_reasons") or [])[:6],
            "swing_score": row.get("swing_score"),
            "swing_signal": str(row.get("swing_signal") or "HOLD").upper(),
            "swing_status": str(row.get("swing_status") or "UNKNOWN"),
        }
        for row in rows[:6]
    ]

    return {
        "available": True,
        "mode": "PAPER_ONLY",
        "venue_mode": str(venue_mode or "UNKNOWN").upper(),
        "symbol_count": int(base.get("symbol_count", len(rows)) or 0),
        "scalp_threshold": float(scalp_threshold),
        "swing_threshold": float(swing_threshold),
        "scalp_scores_at_or_above_threshold": int(base.get("scalp_scores_at_or_above_threshold", 0) or 0),
        "scalp_signals_buy": int(base.get("scalp_signals_buy", 0) or 0),
        "scalp_threshold_met_but_not_buy": int(base.get("scalp_threshold_met_but_not_buy", 0) or 0),
        "scalp_gate_blocked_at_threshold": int(base.get("scalp_gate_blocked_at_threshold", 0) or 0),
        "scalp_gate_block_reasons": dict(sorted(scalp_block_reasons.items(), key=lambda item: (-item[1], item[0]))),
        "scalp_gate_reason_counts_all_symbols": dict(sorted(scalp_reasons_all_symbols.items(), key=lambda item: (-item[1], item[0]))),
        "scalp_pre_calibration_scores_at_or_above_threshold": sum(
            1 for row in rows if bool(row.get("scalp_pre_calibration_threshold_met"))
        ),
        "scalp_pre_calibration_signals_buy": sum(
            1 for row in rows
            if str(row.get("scalp_pre_calibration_signal") or "HOLD").upper() == "BUY"
        ),
        "scalp_pre_calibration_only_signals": sum(
            1 for row in rows
            if str(row.get("scalp_pre_calibration_signal") or "HOLD").upper() == "BUY"
            and str(row.get("scalp_signal") or "HOLD").upper() != "BUY"
        ),
        "scalp_pre_calibration_candidates": pre_calibration_candidates,
        "scalp_status_counts": dict(sorted(scalp_status_counts.items())),
        "swing_scores_at_or_above_threshold": int(base.get("swing_scores_at_or_above_threshold", 0) or 0),
        "swing_signals_buy": int(base.get("swing_signals_buy", 0) or 0),
        "swing_threshold_met_but_not_buy": int(base.get("swing_threshold_met_but_not_buy", 0) or 0),
        "swing_status_counts": dict(sorted(swing_status_counts.items())),
        "buy_symbol_count": int(base.get("buy_symbol_count", 0) or 0),
        "buy_symbols": list(base.get("buy_symbols") or []),
        "threshold_candidates": threshold_candidates,
        "top_scores": top_scores,
        "interpretation": {
            "threshold_met_but_not_buy": "The public score threshold was reached but the strategy did not emit BUY; inspect lane status and gate reasons.",
            "brain_rejections": "Not included here; they are counted separately by the Paper entry funnel after a BUY signal exists.",
            "pre_calibration_shadow": "Reconstructs the prior Scalp score and gate only. It is counterfactual strategy telemetry, not an executable signal and does not bypass current Brain, Risk, Trade Manager, or Execution.",
            "paper_only": True,
            "trading_logic_changed": False,
        },
    }


__all__ = ["build_paper_signal_cycle_summary"]
