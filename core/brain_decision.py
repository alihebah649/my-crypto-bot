"""Brain decision layer for Shadow Trading Bot.

The Brain is deliberately advisory: it can rank and explain a decision, but it
cannot bypass RiskEngine, Exit Policy, or Execution validation.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class BrainDecision:
    action: str
    confidence: float
    reason: str
    exception: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class BrainDecisionEngine:
    """Deterministic policy layer used as the Brain's safe decision core."""

    def __init__(self, min_entry_score: float = 80.0, strong_entry_score: float = 90.0):
        self.min_entry_score = float(min_entry_score)
        self.strong_entry_score = float(strong_entry_score)

    @staticmethod
    def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
        return max(low, min(high, float(value)))

    def decide_entry(
        self,
        score: float,
        signal: str,
        scalp_confirmed_reversal: bool = False,
        risk_locked: bool = False,
        existing_position: bool = False,
        market_regime: str = "NEUTRAL",
        trade_mode: str = "NONE",
        scalp_score: Optional[float] = None,
        swing_score: Optional[float] = None,
        scalp_recovery_confirmation: bool = False,
    ) -> BrainDecision:
        """Evaluate the strategy lane without taking execution authority.

        Scalp has a 65-point context threshold, but entry authority still
        requires either a confirmed 5m reversal or the independent recovery
        trigger introduced by the strategy. Swing keeps its 80-point lane.
        """
        score = self._clamp(score)
        signal = str(signal or "HOLD").upper()
        regime = str(market_regime or "NEUTRAL").upper()
        mode = str(trade_mode or "NONE").upper()
        lane_score = score

        if scalp_score is not None:
            scalp_score = self._clamp(scalp_score)
        if swing_score is not None:
            swing_score = self._clamp(swing_score)

        if risk_locked:
            return BrainDecision("HOLD", 100.0, "RISK_LOCKED", metadata={"authority": "risk"})
        if existing_position:
            return BrainDecision("HOLD", 100.0, "EXISTING_POSITION", metadata={"authority": "portfolio"})
        if signal != "BUY":
            return BrainDecision("HOLD", 90.0, "SIGNAL_NOT_BUY")
        if regime == "BEAR":
            return BrainDecision("HOLD", 90.0, "BEAR_REGIME")

        if mode == "SCALP":
            lane_score = scalp_score if scalp_score is not None else score
            if lane_score < 65.0:
                return BrainDecision("HOLD", self._clamp(lane_score), "SCALP_SCORE_BELOW_THRESHOLD")
            if not (scalp_confirmed_reversal or scalp_recovery_confirmation):
                return BrainDecision("HOLD", self._clamp(lane_score), "NO_CONFIRMED_REVERSAL_OR_RECOVERY")
        elif mode == "SWING":
            lane_score = swing_score if swing_score is not None else score
            if lane_score < self.min_entry_score:
                return BrainDecision("HOLD", self._clamp(lane_score), "SWING_SCORE_BELOW_THRESHOLD")
        else:
            if score < self.min_entry_score:
                return BrainDecision("HOLD", self._clamp(score), "ENTRY_SCORE_BELOW_THRESHOLD")
            if not scalp_confirmed_reversal:
                return BrainDecision("HOLD", self._clamp(score), "NO_CONFIRMED_REVERSAL")

        confidence = self._clamp(lane_score)
        reason = "SCALP_RECOVERY_CONFIRMED" if mode == "SCALP" and scalp_recovery_confirmation and not scalp_confirmed_reversal else "CONFIRMED_ENTRY"
        if confidence >= self.strong_entry_score:
            reason = "HIGH_CONFIDENCE_ENTRY"
        return BrainDecision(
            "BUY",
            confidence,
            reason,
            metadata={
                "trade_mode": mode,
                "scalp_recovery_confirmation": bool(scalp_recovery_confirmation),
            },
        )

    def decide_position(
        self,
        pnl_percent: float,
        hard_stop_triggered: bool = False,
        take_profit_triggered: bool = False,
        recovery_active: bool = False,
        recovery_score: float = 0.0,
        exit_signal: str = "HOLD",
        age_minutes: float = 0.0,
    ) -> BrainDecision:
        """Recommend an action without overriding the authoritative exit layer."""
        pnl_percent = float(pnl_percent)
        recovery_score = self._clamp(recovery_score)
        exit_signal = str(exit_signal or "HOLD").upper()

        if hard_stop_triggered:
            return BrainDecision("SELL", 100.0, "HARD_STOP", metadata={"authoritative": True})
        if take_profit_triggered:
            return BrainDecision("SELL", 100.0, "TAKE_PROFIT", metadata={"authoritative": True})

        if recovery_active and pnl_percent < 0:
            if recovery_score >= 70:
                return BrainDecision("HOLD", recovery_score, "RECOVERY_STRONG", exception="RECOVERY_HOLD")
            return BrainDecision("HOLD", 60.0, "RECOVERY_WAIT", exception="RECOVERY_HOLD")

        if exit_signal == "SELL":
            return BrainDecision("SELL", 85.0, "EXIT_POLICY_SELL_SIGNAL")

        if age_minutes >= 0 and age_minutes > 240 and pnl_percent <= 0:
            return BrainDecision("REVIEW", 70.0, "STALE_POSITION_REVIEW", exception="EXTENDED_HOLD_REVIEW")

        return BrainDecision("HOLD", 60.0, "NO_EXIT_CONDITION")
