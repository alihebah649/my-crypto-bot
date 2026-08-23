"""Exit-policy layer for the modular Trade Manager.

This layer keeps the existing PositionRiskManager rules but fixes two lifecycle
ordering problems at the boundary:
1. a hard stop must always win over Smart Hold/recovery;
2. SCALP positions need a bounded holding window instead of inheriting the
   multi-day Swing hold behavior.

The policy is deliberately conservative: it never widens a stop, never bypasses
fee-aware profit protection, and delegates the existing calculations to the
base PositionRiskManager.
"""
from __future__ import annotations

import time

from .models import Position
from .risk_manager import PositionExitDecision, PositionExitReason, PositionRiskManager


class ExitPolicyPositionRiskManager(PositionRiskManager):
    """PositionRiskManager with explicit SCALP/SWING exit-policy separation."""

    def __init__(self, *args, scalp_max_holding_minutes: float = 120.0, **kwargs):
        if scalp_max_holding_minutes <= 0:
            raise ValueError("scalp_max_holding_minutes must be positive")
        super().__init__(*args, **kwargs)
        self.scalp_max_holding_minutes = float(scalp_max_holding_minutes)

    @staticmethod
    def _trade_mode(position: Position) -> str:
        # New positions store trade_mode in both metadata locations for
        # compatibility. Persisted positions created by earlier revisions may
        # have it in only one location, so recover it before falling back to
        # SWING. This prevents an old SCALP from silently inheriting the
        # unlimited Swing recovery lifecycle after a restart.
        entry_metadata = position.entry_metadata or {}
        metadata = position.metadata or {}
        return str(
            entry_metadata.get("trade_mode", metadata.get("trade_mode", "SWING"))
            or "SWING"
        ).upper()

    def _scalp_timeout(self, position: Position) -> PositionExitDecision:
        if self._trade_mode(position) != "SCALP":
            return PositionExitDecision(False, PositionExitReason.NONE)

        age_minutes = max(0.0, (time.time() - position.opened_at) / 60.0)
        if age_minutes < self.scalp_max_holding_minutes:
            return PositionExitDecision(False, PositionExitReason.NONE)

        pnl = self._get_pnl_percent(position)
        return PositionExitDecision(
            True,
            PositionExitReason.RECOVERY_FAILED,
            position.current_price,
            f"SCALP_TIMEOUT after {age_minutes:.0f}m; P&L {pnl:+.2f}%",
        )

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

        timeout = self._scalp_timeout(position)
        if timeout.should_exit:
            position.metadata["exit_policy"] = "SCALP_TIMEOUT"
            return timeout

        review = self._check_review_required(position)
        if review.review_required:
            return review

        if self._is_profitable(position):
            trailing = self._check_trailing_stop(position)
            if trailing.should_exit:
                return trailing

        hold = self._check_hold_with_market_context(position)
        if hold.should_exit or hold.hold_reason:
            return hold

        return PositionExitDecision(False, PositionExitReason.NONE)


__all__ = ["ExitPolicyPositionRiskManager"]
