"""Decision orchestrator for the Shadow Trading Bot brain.

This first brain layer is intentionally deterministic and provider-agnostic.
A future AI advisor can propose a decision, but the safety gate below remains
mandatory and can veto or constrain any proposal before it reaches the app layer.
"""
from __future__ import annotations

from typing import Protocol

from .models import BrainAction, BrainDecision, BrainInput


class TradingBrainAdvisor(Protocol):
    def advise(self, context: BrainInput) -> BrainDecision: ...


class RuleAdvisor:
    """Baseline advisor used until an external AI model is connected."""

    def advise(self, context: BrainInput) -> BrainDecision:
        signal = str(context.signal.get("signal", "HOLD")).upper()
        mode = str(context.signal.get("trade_mode", "NONE")).upper()
        score = float(context.signal.get("score", 0.0) or 0.0)

        if context.position is not None:
            return BrainDecision(
                action=BrainAction.HOLD,
                confidence=min(1.0, max(0.0, score / 100.0)),
                reason="OPEN_POSITION_REQUIRES_POSITION_MANAGEMENT",
                symbol=context.symbol,
                mode=mode,
            )

        if signal == "BUY" and mode in {"SCALP", "SWING"}:
            return BrainDecision(
                action=BrainAction.OPEN,
                confidence=min(1.0, max(0.0, score / 100.0)),
                reason="STRATEGY_SIGNAL_APPROVED_FOR_BRAIN_REVIEW",
                symbol=context.symbol,
                mode=mode,
            )

        return BrainDecision(
            action=BrainAction.HOLD,
            confidence=min(1.0, max(0.0, score / 100.0)),
            reason="NO_ACTIONABLE_ENTRY_SIGNAL",
            symbol=context.symbol,
            mode=mode,
        )


class TradingBrain:
    """Coordinates strategy intent without owning risk or execution.

    Ordering is deliberate:
      1. hard safety constraints;
      2. advisor proposal;
      3. brain-level normalization;
      4. application layer decides whether to call Trade Manager.

    The brain never calls Binance, never sizes an order, and cannot override a
    risk lock or a hard exit.
    """

    def __init__(self, advisor: TradingBrainAdvisor | None = None) -> None:
        self.advisor = advisor or RuleAdvisor()

    def decide(self, context: BrainInput) -> BrainDecision:
        if context.safety.hard_exit_required:
            return BrainDecision(
                action=BrainAction.CLOSE,
                confidence=1.0,
                reason="HARD_EXIT_REQUIRED",
                symbol=context.symbol,
                mode=str(context.signal.get("trade_mode", "NONE")).upper(),
                constraints=("HARD_EXIT_CANNOT_BE_OVERRIDDEN",),
            )

        if context.safety.risk_locked and context.position is None:
            return BrainDecision(
                action=BrainAction.BLOCK,
                confidence=1.0,
                reason="RISK_LOCKED",
                symbol=context.symbol,
                mode=str(context.signal.get("trade_mode", "NONE")).upper(),
                constraints=("RISK_GATE_IS_AUTHORITATIVE",),
            )

        proposal = self.advisor.advise(context)

        # AI/advisor exceptions are never allowed to create an entry through a
        # locked risk state. They must be represented as a reviewable proposal.
        if proposal.action == BrainAction.OPEN and not context.safety.execution_available:
            return BrainDecision(
                action=BrainAction.REVIEW,
                confidence=proposal.confidence,
                reason="EXECUTION_UNAVAILABLE",
                symbol=context.symbol,
                mode=proposal.mode,
                constraints=("NO_EXECUTION_WHILE_UNAVAILABLE",),
            )

        return proposal


__all__ = ["RuleAdvisor", "TradingBrain", "TradingBrainAdvisor"]
