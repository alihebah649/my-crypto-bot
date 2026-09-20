"""Guarded Brain authority for Paper Trading.

The Brain may accept/reject an entry candidate and may produce a guarded
position/exit recommendation. It never bypasses Risk, Trade Manager, or
Execution safety checks.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .brain_decision import BrainDecision, BrainDecisionEngine
from .brain_market_regime import derive_market_regime


@dataclass(frozen=True)
class BrainAuthorityRecord:
    symbol: str
    trade_mode: str
    stage: str
    strategy_action: str
    strategy_score: float
    brain_action: str
    brain_confidence: float
    brain_reason: str
    allowed: bool
    capture_id: str | None = None
    market_regime: str = "NEUTRAL"
    context: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_version": "v1_guarded",
            "symbol": self.symbol,
            "trade_mode": self.trade_mode,
            "stage": self.stage,
            "strategy_action": self.strategy_action,
            "strategy_score": self.strategy_score,
            "brain_action": self.brain_action,
            "brain_confidence": self.brain_confidence,
            "brain_reason": self.brain_reason,
            "allowed": self.allowed,
            "capture_id": self.capture_id,
            "market_regime": self.market_regime,
            "context": dict(self.context),
        }


class GuardedBrainAuthority:
    """Use the existing deterministic Brain as a pre-Risk decision gate."""

    VERSION = "v1_guarded"

    def __init__(self, brain: BrainDecisionEngine | None = None) -> None:
        self.brain = brain or BrainDecisionEngine()
        self.total_entry_evaluations = 0
        self.entry_allowed = 0
        self.entry_blocked = 0

    @staticmethod
    def _lane_strategy(strategy: Mapping[str, Any], mode: str) -> dict[str, Any]:
        lane = str(mode or "NONE").upper()
        result = dict(strategy)
        result["trade_mode"] = lane
        if lane == "SCALP":
            result["signal"] = "BUY" if strategy.get("scalp_signal") == "BUY" else str(strategy.get("scalp_signal", "HOLD")).upper()
            if strategy.get("scalp_score") is not None:
                result["score"] = strategy.get("scalp_score")
        elif lane == "SWING":
            result["signal"] = "BUY" if strategy.get("swing_signal") == "BUY" else str(strategy.get("swing_signal", "HOLD")).upper()
            if strategy.get("swing_score") is not None:
                result["score"] = strategy.get("swing_score")
        return result

    def evaluate_entry(
        self,
        symbol: str,
        strategy: Mapping[str, Any],
        *,
        trade_mode: str,
        market_regime: str,
        risk_locked: bool = False,
        existing_position: bool = False,
        capture_id: str | None = None,
    ) -> BrainAuthorityRecord:
        lane = self._lane_strategy(strategy, trade_mode)
        symbol_view = derive_market_regime(lane)
        score = float(lane.get("score", 0.0) or 0.0)
        decision: BrainDecision = self.brain.decide_entry(
            score=score,
            signal=str(lane.get("signal", "HOLD")).upper(),
            scalp_confirmed_reversal=bool(lane.get("scalp_confirmed_reversal", False)),
            scalp_recovery_confirmation=bool(lane.get("scalp_recovery_confirmation", False)),
            scalp_score=float(lane.get("scalp_score")) if lane.get("scalp_score") is not None else None,
            swing_score=float(lane.get("swing_score")) if lane.get("swing_score") is not None else None,
            trade_mode=lane.get("trade_mode", "NONE"),
            risk_locked=risk_locked,
            existing_position=existing_position,
            market_regime=str(market_regime or "NEUTRAL").upper(),
            volume_ratio_5m=float(lane.get("volume_ratio_5m")) if lane.get("volume_ratio_5m") is not None else None,
            seller_failure_confirmed=bool(lane.get("seller_failure_confirmed", False)),
            higher_timeframe_bearish=bool(symbol_view.higher_timeframe_bearish),
            symbol_regime=symbol_view.regime,
        )

        allowed = (
            decision.action.upper() == "BUY"
            and not risk_locked
            and not existing_position
        )
        self.total_entry_evaluations += 1
        if allowed:
            self.entry_allowed += 1
        else:
            self.entry_blocked += 1

        return BrainAuthorityRecord(
            symbol=str(symbol).upper(),
            trade_mode=str(trade_mode).upper(),
            stage="ENTRY_GATE",
            strategy_action=str(lane.get("signal", "HOLD")).upper(),
            strategy_score=score,
            brain_action=str(decision.action).upper(),
            brain_confidence=float(decision.confidence),
            brain_reason=decision.reason,
            allowed=allowed,
            capture_id=str(capture_id) if capture_id else None,
            market_regime=str(market_regime or "NEUTRAL").upper(),
            context={
                "authority": self.VERSION,
                "risk_must_still_pass": True,
                "trade_manager_must_still_pass": True,
                "execution_must_still_pass": True,
                "symbol_regime": symbol_view.to_dict(),
                "brain_metadata": dict(decision.metadata),
            },
        )

    def evaluate_position(
        self,
        symbol: str,
        strategy: Mapping[str, Any],
        *,
        pnl_percent: float,
        hard_stop_triggered: bool = False,
        take_profit_triggered: bool = False,
        recovery_active: bool = False,
        recovery_score: float = 0.0,
        exit_signal: str = "HOLD",
        age_minutes: float = 0.0,
        market_regime: str = "NEUTRAL",
    ) -> BrainAuthorityRecord:
        symbol_view = derive_market_regime(strategy)
        decision = self.brain.decide_position(
            pnl_percent=float(pnl_percent),
            hard_stop_triggered=hard_stop_triggered,
            take_profit_triggered=take_profit_triggered,
            recovery_active=recovery_active,
            recovery_score=float(recovery_score),
            exit_signal=exit_signal,
            age_minutes=float(age_minutes),
            market_regime=str(market_regime or "NEUTRAL").upper(),
            symbol_regime=symbol_view.regime,
        )
        return BrainAuthorityRecord(
            symbol=str(symbol).upper(),
            trade_mode=str(strategy.get("trade_mode", "NONE")).upper(),
            stage="POSITION_OBSERVATION",
            strategy_action=str(exit_signal or "HOLD").upper(),
            strategy_score=float(strategy.get("score", 0.0) or 0.0),
            brain_action=str(decision.action).upper(),
            brain_confidence=float(decision.confidence),
            brain_reason=decision.reason,
            allowed=False,
            market_regime=str(market_regime or "NEUTRAL").upper(),
            context={
                "authority": self.VERSION,
                "safety_boundary": "Risk/TradeManager remain authoritative",
                "hard_stop_triggered": bool(hard_stop_triggered),
                "take_profit_triggered": bool(take_profit_triggered),
                "pnl_percent": float(pnl_percent),
                "age_minutes": float(age_minutes),
                "brain_metadata": dict(decision.metadata),
            },
        )

    def snapshot(self) -> dict[str, int | str]:
        return {
            "version": self.VERSION,
            "total_entry_evaluations": self.total_entry_evaluations,
            "entry_allowed": self.entry_allowed,
            "entry_blocked": self.entry_blocked,
        }


__all__ = ["BrainAuthorityRecord", "GuardedBrainAuthority"]
