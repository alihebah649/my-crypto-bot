"""Safe orchestration between Exit Policy, Recovery, Brain and execution.

This layer does not execute orders.  It produces a single lifecycle decision and
keeps the authority boundaries explicit:

1. Authoritative Exit Policy exits cannot be overridden.
2. Hard exits (hard stop / take profit) cannot be overridden.
3. Recovery may hold a losing position, but cannot override an authoritative exit.
4. Normal Brain decisions are advisory and never bypass Risk/Execution layers.
5. A recovery engine score (0..6) is normalized to the Brain's 0..100 scale.
"""

from dataclasses import dataclass, field
from typing import Any, Optional

from core.brain_decision import BrainDecision, BrainDecisionEngine
from core.recovery_engine import RecoveryDecision, RecoveryEngine


@dataclass(frozen=True)
class PositionLifecycleDecision:
    action: str
    reason: str
    authority: str
    brain: Optional[BrainDecision] = None
    recovery: Optional[RecoveryDecision] = None
    metadata: dict[str, Any] = field(default_factory=dict)


class BrainPositionOrchestrator:
    """Coordinate position exit evaluation without performing execution."""

    def __init__(
        self,
        brain: Optional[BrainDecisionEngine] = None,
        recovery: Optional[RecoveryEngine] = None,
    ) -> None:
        self.brain = brain or BrainDecisionEngine()
        self.recovery = recovery or RecoveryEngine()

    @staticmethod
    def _recovery_score_percent(score: int) -> float:
        """RecoveryEngine uses 0..6 while BrainDecisionEngine uses 0..100."""
        return max(0.0, min(100.0, (float(score) / 6.0) * 100.0))

    def evaluate_position(
        self,
        position: Any,
        current_price: float,
        pnl_percent: float,
        *,
        hard_stop_triggered: bool = False,
        take_profit_triggered: bool = False,
        exit_signal: str = "HOLD",
        age_minutes: float = 0.0,
        indicators: Any = None,
        market_regime: str = "BULL",
        current_timestamp: Optional[float] = None,
    ) -> PositionLifecycleDecision:
        """Evaluate one open position on every lifecycle cycle.

        The caller supplies Exit Policy signals. An explicit EXIT is authoritative
        and is evaluated before Recovery/Brain; execution remains outside this layer.
        """
        pnl_percent = float(pnl_percent)
        normalized_exit_signal = str(exit_signal).upper()

        # Authoritative Exit Policy is evaluated before Recovery/Brain.
        if normalized_exit_signal == "EXIT":
            return PositionLifecycleDecision(
                action="SELL",
                reason="EXIT_POLICY",
                authority="EXIT_POLICY",
                metadata={"authoritative": True},
            )

        # Hard exits are absolute and are evaluated before Recovery/Brain.
        if hard_stop_triggered:
            brain = self.brain.decide_position(
                pnl_percent,
                hard_stop_triggered=True,
                age_minutes=age_minutes,
            )
            return PositionLifecycleDecision(
                action="SELL",
                reason="HARD_STOP",
                authority="HARD_EXIT",
                brain=brain,
                metadata={"authoritative": True},
            )

        if take_profit_triggered:
            brain = self.brain.decide_position(
                pnl_percent,
                take_profit_triggered=True,
                age_minutes=age_minutes,
            )
            return PositionLifecycleDecision(
                action="SELL",
                reason="TAKE_PROFIT",
                authority="HARD_EXIT",
                brain=brain,
                metadata={"authoritative": True},
            )

        # A losing position enters Recovery once it crosses the configured
        # recovery threshold. Existing recovery state is preserved by the
        # position object itself.
        if pnl_percent < 0 and self.recovery.should_start_recovery(pnl_percent):
            if not getattr(position, "recovery_mode", False):
                self.recovery.start_recovery(position, current_timestamp)

        recovery_decision: Optional[RecoveryDecision] = None
        recovery_active = bool(getattr(position, "recovery_mode", False))
        recovery_score_percent = 0.0

        if recovery_active:
            raw_score = self.recovery.recovery_score(indicators)
            recovery_score_percent = self._recovery_score_percent(raw_score)
            recovery_decision = self.recovery.should_exit(
                position,
                current_price,
                indicators,
                market_regime=market_regime,
                current_timestamp=current_timestamp,
            )

            # Recovery SELL is a policy decision and must reach execution; the
            # Brain must not turn it back into HOLD.
            if recovery_decision.action == "SELL":
                return PositionLifecycleDecision(
                    action="SELL",
                    reason=recovery_decision.reason,
                    authority="RECOVERY_POLICY",
                    recovery=recovery_decision,
                    metadata={"recovery_score": raw_score},
                )

        brain = self.brain.decide_position(
            pnl_percent,
            recovery_active=recovery_active,
            recovery_score=recovery_score_percent,
            exit_signal=normalized_exit_signal,
            age_minutes=age_minutes,
        )

        return PositionLifecycleDecision(
            action=brain.action,
            reason=brain.reason,
            authority="BRAIN_ADVISORY",
            brain=brain,
            recovery=recovery_decision,
            metadata={
                "recovery_active": recovery_active,
                "recovery_score_percent": recovery_score_percent,
            },
        )
