"""Pure stop, trailing and break-even evaluator from Trade Manager Part 2.

Spot-only integration: all protection math is LONG/owned-asset math.
"""
from __future__ import annotations
from .protection_models import Trade, TradeAction, TradeDecision, TradeSide, TradeStatus

class ProtectionLogicEvaluator:
    """Evaluate protection rules without mutating the trade."""
    def evaluate_trade_protection(self, trade: Trade, current_price: float,
                                  break_even_trigger: float,
                                  trailing_activation: float,
                                  trailing_distance: float,
                                  fees_buffer: float = 0.0) -> TradeDecision:
        if trade.status != TradeStatus.OPEN:
            return TradeDecision(TradeAction.NONE, "TRADE_NOT_OPEN")
        if trade.side is not TradeSide.LONG:
            raise ValueError("Protection evaluator accepts LONG spot positions only")
        if current_price <= 0:
            raise ValueError("current_price must be positive")

        if trade.stop_loss is not None and trade.stop_loss > 0 and current_price <= trade.stop_loss:
            return TradeDecision(
                TradeAction.STOP_LOSS, "STOP_LOSS_OR_TRAILING_HIT",
                metadata={"trigger_price": trade.stop_loss, "exit_price": current_price},
            )

        trailing = self._evaluate_trailing(
            trade, current_price, trailing_activation, trailing_distance
        )
        if trailing.action != TradeAction.NONE or trailing.update_highest or trailing.activate_trailing:
            return trailing

        break_even = self._evaluate_break_even(
            trade, current_price, break_even_trigger, fees_buffer
        )
        if break_even.action != TradeAction.NONE:
            return break_even

        if trade.trailing_active:
            return TradeDecision(TradeAction.NONE, "HOLD_TRAILING_ACTIVE")

        if trade.take_profit is not None and trade.take_profit > 0 and current_price >= trade.take_profit:
            return TradeDecision(TradeAction.CLOSE, "TAKE_PROFIT_HIT")

        return TradeDecision(
            TradeAction.NONE, "HOLD", stop_loss=trade.stop_loss, take_profit=trade.take_profit
        )

    def _evaluate_trailing(self, trade: Trade, current_price: float,
                           trailing_activation: float, trailing_distance: float) -> TradeDecision:
        if not trade.trailing_enabled:
            return TradeDecision(TradeAction.NONE, "HOLD")
        profit = (current_price - trade.entry_price) / trade.entry_price
        has_new_peak = current_price > trade.highest_price
        should_activate = not trade.trailing_active and profit >= trailing_activation
        trailing_live = trade.trailing_active or should_activate

        if not trailing_live:
            if has_new_peak:
                return TradeDecision(
                    TradeAction.NONE, "NEW_HIGHEST_REACHED",
                    update_highest=True, new_highest=current_price
                )
            return TradeDecision(TradeAction.NONE, "HOLD")

        working_peak = max(trade.highest_price, current_price)
        new_stop = working_peak * (1.0 - trailing_distance)
        current_stop = trade.stop_loss if trade.stop_loss is not None else 0.0
        improved = new_stop > current_stop
        metadata = {
            "trailing_state_active": trailing_live,
            "profit_percent": profit * 100.0,
            "calculated_new_stop": new_stop,
            "peak_used": working_peak,
        }
        if improved:
            return TradeDecision(
                TradeAction.UPDATE_STOP,
                "TRAILING_STOP_ACTIVATED" if should_activate else "TRAILING_STOP_UPDATED",
                stop_loss=new_stop, update_highest=has_new_peak,
                new_highest=current_price if has_new_peak else None,
                activate_trailing=should_activate, metadata=metadata,
            )
        if has_new_peak:
            return TradeDecision(
                TradeAction.NONE, "PEAK_UPDATED_WITHOUT_STOP_MOVE",
                update_highest=True, new_highest=current_price,
                activate_trailing=should_activate, metadata=metadata,
            )
        return TradeDecision(TradeAction.NONE, "HOLD", activate_trailing=should_activate, metadata=metadata)

    def _evaluate_break_even(self, trade: Trade, current_price: float,
                             break_even_trigger: float, fees_buffer: float) -> TradeDecision:
        if not trade.break_even_enabled or trade.break_even_done:
            return TradeDecision(TradeAction.NONE, "HOLD")
        profit = (current_price - trade.entry_price) / trade.entry_price
        if profit < break_even_trigger:
            return TradeDecision(TradeAction.NONE, "HOLD")
        new_stop = trade.entry_price + max(fees_buffer, 0.0)
        current_stop = trade.stop_loss if trade.stop_loss is not None else 0.0
        if new_stop > current_stop:
            return TradeDecision(
                TradeAction.ACTIVATE_BREAK_EVEN, "BREAK_EVEN_ACTIVATED",
                stop_loss=new_stop, break_even_done=True,
            )
        return TradeDecision(TradeAction.NONE, "HOLD")
