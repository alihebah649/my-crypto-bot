"""Exit-policy layer for the modular Trade Manager.

This layer keeps the existing PositionRiskManager rules while enforcing the
current lifecycle contract:
1. a hard stop must always win over Smart Hold/recovery;
2. SCALP and SWING positions share the same long-lived recovery lifecycle;
3. elapsed holding time alone never forces an exit.

Timeout-based forced exits were deliberately removed. Recovery/review policy
is responsible for deciding what to do with a losing position, while the
controller remains responsible for actual execution.
"""
from __future__ import annotations

from .models import Position
from .risk_manager import PositionExitDecision, PositionExitReason, PositionRiskManager


class ExitPolicyPositionRiskManager(PositionRiskManager):
    """PositionRiskManager with explicit lifecycle ordering and no timeout exit."""

    @staticmethod
    def _trade_mode(position: Position) -> str:
        entry_metadata = position.entry_metadata or {}
        metadata = position.metadata or {}
        return str(
            entry_metadata.get("trade_mode", metadata.get("trade_mode", "SWING"))
            or "SWING"
        ).upper()

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

        stop = self._check_stop_loss(position)
        if stop.should_exit:
            return stop

        take_profit = self._check_take_profit(position)
        if take_profit.should_exit:
            return take_profit

        review = self._check_review_required(position)
        if review.review_required:
            return review

        if self._is_profitable(position):
            trailing = self._check_trailing_stop(position)
            if trailing.should_exit:
                return trailing

        # No elapsed-time / SCALP timeout exit. A losing position may enter
        # HOLD and continue through Smart Hold -> Recovery -> Review.
        hold = self._check_hold_with_market_context(position)
        if hold.should_exit or hold.hold_reason:
            return hold

        return PositionExitDecision(False, PositionExitReason.NONE)


__all__ = ["ExitPolicyPositionRiskManager"]
