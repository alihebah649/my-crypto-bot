"""Runtime adapter for Brain shadow-mode entry observations.

This module is observational only. It evaluates the existing Brain decision
core beside the live strategy decision and never calls Risk, Trade Manager,
or Execution.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Mapping

from .brain_context_fingerprint import brain_context_fingerprint
from .brain_decision import BrainDecision, BrainDecisionEngine


@dataclass(frozen=True)
class BrainShadowEntryRecord:
    timestamp: float
    context_fingerprint: str
    symbol: str
    trade_mode: str
    strategy_action: str
    strategy_score: float
    brain_action: str
    brain_confidence: float
    brain_reason: str
    agreement: bool
    context: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "context_fingerprint": self.context_fingerprint,
            "symbol": self.symbol,
            "trade_mode": self.trade_mode,
            "strategy_action": self.strategy_action,
            "strategy_score": self.strategy_score,
            "brain_action": self.brain_action,
            "brain_confidence": self.brain_confidence,
            "brain_reason": self.brain_reason,
            "agreement": self.agreement,
            "context": dict(self.context),
        }


class BrainShadowRuntime:
    """Evaluate Brain advice in parallel without changing execution authority."""

    def __init__(self, brain: BrainDecisionEngine | None = None) -> None:
        self.brain = brain or BrainDecisionEngine()
        self.last_records: dict[str, BrainShadowEntryRecord] = {}
        self.total = 0
        self.agreements = 0
        self.disagreements = 0

    def evaluate_entry(
        self,
        symbol: str,
        strategy: Mapping[str, Any],
        *,
        risk_locked: bool = False,
        existing_position: bool = False,
        market_regime: str = "NEUTRAL",
    ) -> BrainShadowEntryRecord:
        context = dict(strategy)
        context["symbol"] = symbol
        mode = str(strategy.get("trade_mode", "NONE")).upper()
        strategy_action = str(strategy.get("signal", "HOLD")).upper()
        score = float(strategy.get("score", 0.0) or 0.0)
        brain_decision: BrainDecision = self.brain.decide_entry(
            score=score,
            signal=strategy_action,
            scalp_confirmed_reversal=bool(strategy.get("scalp_confirmed_reversal", False)),
            risk_locked=risk_locked,
            existing_position=existing_position,
            market_regime=market_regime,
        )
        brain_action = str(brain_decision.action).upper()
        # OPEN/BUY are equivalent entry intents for comparison only.
        strategy_entry = strategy_action == "BUY"
        brain_entry = brain_action == "BUY"
        agreement = strategy_entry == brain_entry
        record = BrainShadowEntryRecord(
            timestamp=time.time(),
            context_fingerprint=brain_context_fingerprint(context),
            symbol=symbol,
            trade_mode=mode,
            strategy_action=strategy_action,
            strategy_score=score,
            brain_action=brain_action,
            brain_confidence=float(brain_decision.confidence),
            brain_reason=brain_decision.reason,
            agreement=agreement,
            context=context,
        )
        self.last_records[symbol] = record
        self.total += 1
        if agreement:
            self.agreements += 1
        else:
            self.disagreements += 1
        return record

    def snapshot(self) -> dict[str, int]:
        return {
            "total": self.total,
            "agreements": self.agreements,
            "disagreements": self.disagreements,
        }


__all__ = ["BrainShadowEntryRecord", "BrainShadowRuntime"]
