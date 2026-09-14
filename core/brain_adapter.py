"""Adapters from the existing Shadow runtime into Brain contracts.

This module is intentionally read-only: it translates observations and never
executes, closes, opens, or mutates a trade.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional

from .brain_models import BrainMarketState, BrainPosition, BrainRiskState


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def market_from_score(symbol: str, score: Mapping[str, Any]) -> BrainMarketState:
    return BrainMarketState(
        symbol=symbol,
        signal=str(score.get("signal", "HOLD")),
        score=_f(score.get("score")),
        scalp_score=_f(score.get("scalp_score")),
        swing_score=_f(score.get("swing_score")),
        regime=str(score.get("regime", "UNKNOWN")),
        volatility=str(score.get("volatility", "UNKNOWN")),
        macro_support=bool(
            score.get("scalp_gate")
            or any("MACRO_SUPPORT" in str(x) for x in score.get("scalp_reasons", []))
            or any("15M_BOLLINGER" in str(x) for x in score.get("reasons", []))
        ),
        confirmed_reversal=bool(score.get("scalp_confirmed_reversal")),
        volume_ratio_5m=_f(score.get("volume_ratio_5m")),
        rsi_5m=_f(score.get("rsi5m"), None) if score.get("rsi5m") is not None else None,
        metadata={
            "trade_mode": score.get("trade_mode", "NONE"),
            "scalp_gate": bool(score.get("scalp_gate")),
            "scalp_gate_reasons": list(score.get("scalp_gate_reasons", [])),
            "pattern": score.get("pattern", "NEUTRAL"),
            "pattern_confirmed": bool(score.get("pattern_confirmed")),
            "reasons": list(score.get("reasons", [])),
        },
    )


def risk_from_runtime(runtime: Any) -> BrainRiskState:
    config = getattr(runtime, "risk_config", None)
    exposure = getattr(config, "exposure", None)
    positions = list(runtime.repository.get_open_positions())
    max_open = int(getattr(exposure, "max_open_positions", 0) or 0)
    balance = getattr(runtime.execution_adapter, "balance", None)
    cash = _f(getattr(balance, "cash", 0.0))
    locked = False
    lock_reason = ""
    risk_controller = getattr(runtime, "risk_controller", None)
    state = getattr(risk_controller, "state", None)
    if state is not None:
        locked = bool(getattr(state, "locked", False))
        lock_reason = str(getattr(state, "lock_reason", ""))
    return BrainRiskState(
        locked=locked,
        lock_reason=lock_reason,
        open_positions=len(positions),
        max_open_positions=max_open,
        free_balance=cash,
        metadata={"source": "shadow_runtime", "position_count": len(positions)},
    )


def position_from_runtime(position: Any) -> BrainPosition:
    mode = str(position.entry_metadata.get("trade_mode", "SWING")).upper()
    return BrainPosition(
        symbol=str(position.symbol),
        trade_mode=mode,
        pnl_percent=_f(getattr(position, "gross_pnl", 0.0)) / max(_f(getattr(position, "entry_price", 0.0)) * _f(getattr(position, "quantity", 0.0)), 1e-12) * 100.0,
        age_minutes=_f(position.metadata.get("age_minutes", 0.0)),
        exit_candidate=bool(position.exit_metadata.get("exit_candidate", False)),
        hard_stop=bool(position.exit_metadata.get("hard_stop_triggered", False)),
        timeout=bool(position.exit_metadata.get("scalp_timeout", False)),
        metadata={"status": str(getattr(position.status, "name", position.status))},
    )


def positions_from_runtime(runtime: Any) -> Iterable[BrainPosition]:
    return [position_from_runtime(p) for p in runtime.repository.get_open_positions()]
