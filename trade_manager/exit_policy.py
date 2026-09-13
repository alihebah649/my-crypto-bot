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

import time

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

    @staticmethod
    def _pnl_percent(position: Position) -> float:
        if position.entry_price <= 0:
            return 0.0
        return ((position.current_price - position.entry_price) / position.entry_price) * 100.0

    def _record_exit_trace(self, position: Position, decision: PositionExitDecision) -> None:
        """Persist a non-invasive explanation of the latest exit evaluation.

        This is diagnostics only. It does not alter the exit decision or any
        risk threshold. The trace lives with the position so it survives the
        normal repository persistence path and can later be joined to the
        position_id / closed-position history.
        """
        now = time.time()
        recovery_start = position.entered_hold_at
        days_in_recovery = ((now - recovery_start) / 86400.0) if recovery_start else 0.0
        context = position.hold_context or {}
        trailing_state = {
            "highest_price": position.highest_price,
            "max_profit_percent": position.max_profit_percent,
            "active": position.max_profit_percent > 0.0 and self._is_profitable(position),
        }
        trace = {
            "symbol": position.symbol,
            "position_id": position.position_id,
            "trade_mode": self._trade_mode(position),
            "entry_price": position.entry_price,
            "current_price": position.current_price,
            "pnl_percent": self._pnl_percent(position),
            "stop_loss": position.stop_loss,
            "take_profit": position.take_profit,
            "trailing": trailing_state,
            "recovery_mode": position.status.name == "HOLD" or bool(recovery_start),
            "recovery_start_time": recovery_start,
            "recovery_score": float(decision.recovery_score or context.get("recovery_potential", 0.0) or 0.0),
            "market_regime": context.get("market", {}).get("overall") if isinstance(context.get("market"), dict) else None,
            "days_in_recovery": max(0.0, days_in_recovery),
            "decision": "SELL" if decision.should_exit else ("REVIEW_REQUIRED" if decision.review_required else "HOLD" if decision.hold_reason else "NONE"),
            "decision_reason": decision.reason.name,
            "hold_reason": decision.hold_reason or position.hold_reason or "",
            "decision_message": decision.message or "",
            "evaluation_timestamp": now,
        }
        position.metadata["exit_decision_trace"] = trace

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
            self._record_exit_trace(position, stop)
            return stop

        take_profit = self._check_take_profit(position)
        if take_profit.should_exit:
            self._record_exit_trace(position, take_profit)
            return take_profit

        review = self._check_review_required(position)
        if review.review_required:
            self._record_exit_trace(position, review)
            return review

        if self._is_profitable(position):
            trailing = self._check_trailing_stop(position)
            if trailing.should_exit:
                self._record_exit_trace(position, trailing)
                return trailing

        # No elapsed-time / SCALP timeout exit. A losing position may enter
        # HOLD and continue through Smart Hold -> Recovery -> Review.
        hold = self._check_hold_with_market_context(position)
        if hold.should_exit or hold.hold_reason:
            self._record_exit_trace(position, hold)
            return hold

        decision = PositionExitDecision(False, PositionExitReason.NONE)
        self._record_exit_trace(position, decision)
        return decision


__all__ = ["ExitPolicyPositionRiskManager"]
