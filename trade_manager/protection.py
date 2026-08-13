"""Pure stop, trailing and break-even evaluator from Part 2."""

from __future__ import annotations

from .protection_models import Trade, TradeAction, TradeDecision, TradeSide, TradeStatus


class ProtectionLogicEvaluator:
    """Evaluate protection rules without mutating the trade."""

    def evaluate_trade_protection(
        self,
        trade: Trade,
        current_price: float,
        break_even_trigger: float,
        trailing_activation: float,
        trailing_distance: float,
        fees_buffer: float = 0.0,
    ) -> TradeDecision:
        if trade.status != TradeStatus.OPEN:
            return TradeDecision(TradeAction.NONE, "TRADE_NOT_OPEN")

        is_long = trade.side == TradeSide.LONG
        direction = 1 if is_long else -1

        if trade.stop_loss is not None and trade.stop_loss > 0:
            stop_hit = (is_long and current_price <= trade.stop_loss) or (
                not is_long and current_price >= trade.stop_loss
            )
            if stop_hit:
                return TradeDecision(
                    TradeAction.STOP_LOSS,
                    "STOP_LOSS_OR_TRAILING_HIT",
                    metadata={"trigger_price": trade.stop_loss, "exit_price": current_price},
                )

        trailing = self._evaluate_trailing(
            trade, current_price, trailing_activation, trailing_distance, direction
        )
        if (
            trailing.action != TradeAction.NONE
            or trailing.update_highest
            or trailing.update_lowest
            or trailing.activate_trailing
        ):
            return trailing

        break_even = self._evaluate_break_even(
            trade, current_price, break_even_trigger, fees_buffer, direction
        )
        if break_even.action != TradeAction.NONE:
            return break_even

        if trade.trailing_active:
            return TradeDecision(TradeAction.NONE, "HOLD_TRAILING_ACTIVE")

        if trade.take_profit is not None and trade.take_profit > 0:
            tp_hit = (is_long and current_price >= trade.take_profit) or (
                not is_long and current_price <= trade.take_profit
            )
            if tp_hit:
                return TradeDecision(TradeAction.CLOSE, "TAKE_PROFIT_HIT")

        return TradeDecision(
            TradeAction.NONE,
            "HOLD",
            stop_loss=trade.stop_loss,
            take_profit=trade.take_profit,
        )

    def _evaluate_trailing(
        self,
        trade: Trade,
        current_price: float,
        trailing_activation: float,
        trailing_distance: float,
        direction: int,
    ) -> TradeDecision:
        if not trade.trailing_enabled:
            return TradeDecision(TradeAction.NONE, "HOLD")

        profit = (current_price - trade.entry_price) / trade.entry_price * direction
        has_new_peak = direction == 1 and current_price > trade.highest_price
        has_new_trough = direction == -1 and current_price < trade.lowest_price

        should_activate = not trade.trailing_active and profit >= trailing_activation
        trailing_live = trade.trailing_active or should_activate

        if not trailing_live:
            if has_new_peak:
                return TradeDecision(
                    TradeAction.NONE, "NEW_HIGHEST_REACHED", True, None,
                    True, current_price, False, None
                )
            if has_new_trough:
                return TradeDecision(
                    TradeAction.NONE, "NEW_LOWEST_REACHED", False, None,
                    False, None, True, current_price
                )
            return TradeDecision(TradeAction.NONE, "HOLD")

        working_peak = (
            max(trade.highest_price, current_price)
            if direction == 1
            else min(trade.lowest_price, current_price)
        )

        if direction == 1:
            new_stop = working_peak * (1.0 - trailing_distance)
            current_stop = trade.stop_loss if trade.stop_loss is not None else 0.0
            improved = new_stop > current_stop
        else:
            new_stop = working_peak * (1.0 + trailing_distance)
            current_stop = trade.stop_loss if trade.stop_loss is not None else float("inf")
            improved = new_stop < current_stop

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
                stop_loss=new_stop,
                update_highest=has_new_peak,
                new_highest=current_price if has_new_peak else None,
                update_lowest=has_new_trough,
                new_lowest=current_price if has_new_trough else None,
                activate_trailing=should_activate,
                metadata=metadata,
            )

        if has_new_peak or has_new_trough:
            return TradeDecision(
                TradeAction.NONE,
                "PEAK_UPDATED_WITHOUT_STOP_MOVE",
                update_highest=has_new_peak,
                new_highest=current_price if has_new_peak else None,
                update_lowest=has_new_trough,
                new_lowest=current_price if has_new_trough else None,
                activate_trailing=should_activate,
                metadata=metadata,
            )

        return TradeDecision(
            TradeAction.NONE, "HOLD", activate_trailing=should_activate, metadata=metadata
        )

    def _evaluate_break_even(
        self,
        trade: Trade,
        current_price: float,
        break_even_trigger: float,
        fees_buffer: float,
        direction: int,
    ) -> TradeDecision:
        if not trade.break_even_enabled or trade.break_even_done:
            return TradeDecision(TradeAction.NONE, "HOLD")

        profit = (current_price - trade.entry_price) / trade.entry_price * direction
        if profit < break_even_trigger:
            return TradeDecision(TradeAction.NONE, "HOLD")

        fees_buffer = max(fees_buffer, 0.0)
        new_stop = trade.entry_price + fees_buffer * direction

        if direction == 1:
            current_stop = trade.stop_loss if trade.stop_loss is not None else 0.0
            improved = new_stop > current_stop
        else:
            current_stop = trade.stop_loss if trade.stop_loss is not None else float("inf")
            improved = new_stop < current_stop

        if improved:
            return TradeDecision(
                TradeAction.ACTIVATE_BREAK_EVEN,
                "BREAK_EVEN_ACTIVATED",
                stop_loss=new_stop,
                break_even_done=True,
            )

        return TradeDecision(TradeAction.NONE, "HOLD")
