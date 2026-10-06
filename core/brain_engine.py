"""Deterministic Brain orchestration for the trading bot.

This is the first Brain stage: it coordinates existing observations and
policies without executing trades. A future AI provider can supply advisory
scores/context behind the same contract, while deterministic safety rules
remain authoritative.
"""
from __future__ import annotations

from typing import Optional

from .brain_models import (
    BrainAction,
    BrainDecision,
    BrainMarketState,
    BrainPosition,
    BrainRiskState,
)


class TradingBrain:
    """Decision coordinator sitting above strategy/risk/exit components."""

    def decide(
        self,
        *,
        market: BrainMarketState,
        risk: BrainRiskState,
        position: Optional[BrainPosition] = None,
    ) -> BrainDecision:
        symbol = market.symbol

        # Safety hierarchy: an actual hard exit can never be vetoed by an
        # advisory Brain decision or by Smart Hold/recovery reasoning.
        if position is not None and position.hard_stop:
            return BrainDecision(
                BrainAction.EXIT,
                symbol,
                1.0,
                "HARD_STOP_PRIORITY",
                hard_constraint=True,
                metadata={"trade_mode": position.trade_mode},
            )

        if position is not None and position.timeout:
            return BrainDecision(
                BrainAction.EXIT,
                symbol,
                1.0,
                "SCALP_TIMEOUT_PRIORITY" if position.trade_mode.upper() == "SCALP" else "POSITION_TIMEOUT",
                hard_constraint=True,
                metadata={"trade_mode": position.trade_mode},
            )

        if position is not None and position.exit_candidate:
            return BrainDecision(
                BrainAction.EXIT,
                symbol,
                min(1.0, max(0.0, 0.70 + abs(position.pnl_percent) / 100.0)),
                "EXIT_POLICY_CANDIDATE",
                metadata={"pnl_percent": position.pnl_percent},
            )

        # Risk remains authoritative for entries. The Brain may recognize a
        # setup but must never unlock a risk lock or exceed position limits.
        if risk.locked:
            return BrainDecision(
                BrainAction.BLOCK,
                symbol,
                1.0,
                f"RISK_LOCKED:{risk.lock_reason or 'UNKNOWN'}",
                hard_constraint=True,
            )

        if risk.max_open_positions > 0 and risk.open_positions >= risk.max_open_positions:
            return BrainDecision(
                BrainAction.BLOCK,
                symbol,
                1.0,
                "MAX_OPEN_POSITIONS",
                hard_constraint=True,
            )

        signal = market.signal.upper()
        if signal != "BUY":
            return BrainDecision(
                BrainAction.HOLD,
                symbol,
                0.50,
                "NO_ENTRY_SIGNAL",
                metadata={"signal": signal, "score": market.score},
            )

        # Keep the current lane contracts explicit. The Brain coordinates the
        # strategy result; it does not replace the strategy thresholds.
        mode = "SCALP" if market.scalp_score >= 65 else "SWING" if market.swing_score >= 80 else "NONE"
        if mode == "SCALP":
            if not market.confirmed_reversal or not market.macro_support:
                return BrainDecision(
                    BrainAction.REVIEW,
                    symbol,
                    0.60,
                    "SCALP_SETUP_INCOMPLETE",
                    metadata={"scalp_score": market.scalp_score},
                )
        elif mode == "SWING":
            pass
        else:
            return BrainDecision(
                BrainAction.REVIEW,
                symbol,
                0.55,
                "SCORE_BELOW_ENTRY_LANES",
                metadata={"scalp_score": market.scalp_score, "swing_score": market.swing_score},
            )

        confidence = min(1.0, max(0.0, (market.scalp_score if mode == "SCALP" else market.swing_score) / 100.0))
        return BrainDecision(
            BrainAction.ENTER,
            symbol,
            confidence,
            f"{mode}_SETUP_APPROVED_FOR_RISK_REVIEW",
            metadata={
                "trade_mode": mode,
                "signal": signal,
                "score": market.score,
                "scalp_score": market.scalp_score,
                "swing_score": market.swing_score,
            },
        )


__all__ = ["TradingBrain"]
