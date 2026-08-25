"""Exit-policy layer for the modular Trade Manager.

This layer keeps the existing PositionRiskManager rules while enforcing the
lifecycle ordering at the boundary:
1. a hard stop must always win over Smart Hold/recovery;
2. fee-aware profit protection and trailing exits remain authoritative;
3. SCALP positions no longer have an automatic time-based exit.

Holding duration is observational metadata only. It is not an exit trigger.
Recovery remains governed by the existing market-context and recovery rules.
"""
from __future__ import annotations

from .models import Position
from .risk_manager import PositionExitDecision, PositionExitReason, PositionRiskManager


class ExitPolicyPositionRiskManager(PositionRiskManager):
    """PositionRiskManager with explicit exit-policy ordering.

    SCALP and SWING share the same authoritative protection boundary.  The
    previous SCALP 120-minute timeout has intentionally been removed so that
    elapsed time alone cannot force an exit or masquerade as recovery failure.
    """

    def evaluate(self, position: Position) -> PositionExitDecision:
        self._update_position_metrics(position)
        position.hold_context = self._get_market_context(position.symbol)

        if "initial_stop_loss" not in position.metadata:
            position.metadata["initial_stop_loss"] = position.stop_loss

        if self.should_move_to_break_even(position):
            be = self.calculator.break_even_price(position)
            if position.stop_loss < be:
                position.stop_loss = be
                position.metadata["break_even_activated"] = True

        # Hard protection remains first.
        stop = self._check_stop_loss(position)
        if stop.should_exit:
            return stop

        # Configured TP is an activation trigger when adaptive trailing TP is
        # enabled; otherwise it remains an authoritative hard exit.
        take_profit = self._check_take_profit(position)
        if take_profit.should_exit:
            return take_profit

        # No automatic SCALP timeout here. Elapsed time is diagnostic only and
        # must never be converted into RECOVERY_FAILED.

        review = self._check_review_required(position)
        if review.review_required:
            return review

        if self._is_profitable(position):
            trailing = self._check_trailing_stop(position)
            if trailing.should_exit:
                return trailing

        # Losing positions are handled by the existing Smart Hold / recovery
        # policy. A genuine RECOVERY_FAILED decision is still possible when
        # its configured loss/recovery conditions are met.
        hold = self._check_hold_with_market_context(position)
        if hold.should_exit or hold.hold_reason:
            return hold

        return PositionExitDecision(False, PositionExitReason.NONE)


__all__ = ["ExitPolicyPositionRiskManager"]
