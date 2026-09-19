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
        volume_ratio_5m: Optional[float] = None,
        seller_failure_confirmed: bool = False,
        higher_timeframe_bearish: bool = False,
        symbol_regime: Optional[str] = None,
    ) -> BrainDecision:
        """Evaluate the strategy lane without taking execution authority.

        Scalp has a 65-point context threshold, but entry authority still
        requires either a confirmed 5m reversal or the independent recovery
        trigger introduced by the strategy. Swing keeps its 80-point lane.
        """
        score = self._clamp(score)
        signal = str(signal or "HOLD").upper()
        regime = str(market_regime or "NEUTRAL").upper()
        local_regime = str(symbol_regime or market_regime or "NEUTRAL").upper()
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

        # A true downtrend (broad Bear + local Bear) does not authorize normal
        # long entries. The Brain can recognize only a short-lived counter-trend
        # scalp when structural reversal quality is confirmed.
        if regime == "BEAR" and local_regime == "BEAR":
            if mode != "SCALP":
                return BrainDecision("HOLD", 95.0, "BEAR_SWING_DISABLED")
            lane_score = scalp_score if scalp_score is not None else score
            if lane_score < 65.0:
                return BrainDecision("HOLD", self._clamp(lane_score), "BEAR_SCALP_SCORE_BELOW_THRESHOLD")
            if not scalp_confirmed_reversal:
                return BrainDecision("HOLD", self._clamp(lane_score), "BEAR_NO_CONFIRMED_REVERSAL")
            if not seller_failure_confirmed:
                return BrainDecision("HOLD", self._clamp(lane_score), "BEAR_SELLER_FAILURE_NOT_CONFIRMED")
            if volume_ratio_5m is None or float(volume_ratio_5m) < 1.0:
                return BrainDecision("HOLD", self._clamp(lane_score), "BEAR_VOLUME_NOT_CONFIRMING")
            if higher_timeframe_bearish:
                return BrainDecision("HOLD", self._clamp(lane_score), "BEAR_HIGHER_TIMEFRAME_CONTINUATION")
            return BrainDecision(
                "BUY",
                self._clamp(lane_score),
                "BEAR_COUNTERTREND_SCALP_CONFIRMED",
                metadata={
                    "trade_mode": "SCALP",
                    "market_regime": "BEAR",
                    "countertrend": True,
                    "scalp_recovery_confirmation": bool(scalp_recovery_confirmation),
                },
            )

        if regime == "BEAR" and local_regime == "BULL" and mode == "SWING":
            lane_score = swing_score if swing_score is not None else score
            if lane_score < 90.0:
                return BrainDecision("HOLD", self._clamp(lane_score), "BEAR_MARKET_SWING_STRENGTH_REQUIRED")
            if higher_timeframe_bearish:
                return BrainDecision("HOLD", self._clamp(lane_score), "BEAR_MARKET_HIGHER_TIMEFRAME_CONFLICT")

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
        market_regime: str = "NEUTRAL",
    ) -> BrainDecision:
        """Recommend an action without overriding the authoritative exit layer."""
        pnl_percent = float(pnl_percent)
        recovery_score = self._clamp(recovery_score)
        exit_signal = str(exit_signal or "HOLD").upper()
        regime = str(market_regime or "NEUTRAL").upper()
        local_regime = str(symbol_regime or market_regime or "NEUTRAL").upper()

        if hard_stop_triggered:
            return BrainDecision("SELL", 100.0, "HARD_STOP", metadata={"authoritative": True})
        if take_profit_triggered:
            return BrainDecision("SELL", 100.0, "TAKE_PROFIT", metadata={"authoritative": True})

        if exit_signal == "SELL":
            return BrainDecision("SELL", 85.0, "EXIT_POLICY_SELL_SIGNAL")

        # In a bear regime the Brain becomes more protective without touching
        # hard-stop or Exit Policy authority. Positive positions can be protected
        # early; losing positions are sold only when recovery is weak or the loss
        # has remained unresolved long enough to represent a deteriorating thesis.
        if regime == "BEAR":
            if pnl_percent > 0 and local_regime != "BULL":
                return BrainDecision("SELL", 80.0, "BEAR_PROFIT_PROTECTION")
            if recovery_active and recovery_score < 50.0:
                return BrainDecision("SELL", 80.0, "BEAR_RECOVERY_WEAK")
            if pnl_percent < 0 and age_minutes >= 30.0 and recovery_score < 70.0:
                return BrainDecision("SELL", 75.0, "BEAR_LOSS_REVIEW")
            if recovery_active and recovery_score >= 70.0:
                return BrainDecision("HOLD", recovery_score, "BEAR_RECOVERY_STRONG", exception="RECOVERY_HOLD")

        if recovery_active and pnl_percent < 0:
            if recovery_score >= 70:
                return BrainDecision("HOLD", recovery_score, "RECOVERY_STRONG", exception="RECOVERY_HOLD")
            return BrainDecision("HOLD", 60.0, "RECOVERY_WAIT", exception="RECOVERY_HOLD")

        if age_minutes >= 0 and age_minutes > 240 and pnl_percent <= 0:
            return BrainDecision("REVIEW", 70.0, "STALE_POSITION_REVIEW", exception="EXTENDED_HOLD_REVIEW")

        return BrainDecision("HOLD", 60.0, "NO_EXIT_CONDITION")
