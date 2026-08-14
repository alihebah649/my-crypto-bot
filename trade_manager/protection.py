from __future__ import annotations
import time
from .models import ExitReason, ManagedPosition, ProtectionAction, ProtectionDecision, TradeManagerConfig

class ProtectionLogicEvaluator:
    """Pure protection evaluator: stop -> break-even -> ATR trailing -> TP -> review."""
    def __init__(self, config: TradeManagerConfig | None = None): self.config = config or TradeManagerConfig()
    def evaluate(self, position: ManagedPosition, current_price: float, atr: float | None = None) -> ProtectionDecision:
        if position.status != "OPEN": return ProtectionDecision(reason="POSITION_NOT_OPEN")
        if current_price <= 0: raise ValueError("Invalid current price")
        position.current_price = current_price
        position.highest_price = max(position.highest_price, current_price)
        position.lowest_price = min(position.lowest_price, current_price)
        position.unrealized_pnl = (current_price - position.entry_price) * position.quantity
        if position.stop_loss > 0 and current_price <= position.stop_loss:
            return ProtectionDecision(ProtectionAction.CLOSE_POSITION, "STOP_LOSS_HIT", close_reason=ExitReason.STOP_LOSS)
        profit = (current_price - position.entry_price) / position.entry_price
        if not position.break_even_done and profit >= self.config.break_even_trigger:
            buffer = self.config.fee_rate * 2.0 + self.config.slippage_rate
            new_stop = position.entry_price * (1.0 + buffer)
            if new_stop > position.stop_loss:
                return ProtectionDecision(ProtectionAction.MOVE_TO_BREAK_EVEN, "BREAK_EVEN_ACTIVATED", new_stop_loss=new_stop, close_reason=ExitReason.BREAK_EVEN)
        if profit >= self.config.trailing_activation:
            atr_value = atr if atr and atr > 0 else position.atr_at_entry
            if atr_value > 0:
                candidate = position.highest_price - atr_value * self.config.trailing_atr_multiplier
                if candidate > position.stop_loss:
                    return ProtectionDecision(ProtectionAction.UPDATE_STOP, "TRAILING_STOP_UPDATED", new_stop_loss=candidate, close_reason=ExitReason.TRAILING_STOP)
        if not position.trailing_active and position.take_profit and current_price >= position.take_profit:
            return ProtectionDecision(ProtectionAction.CLOSE_POSITION, "TAKE_PROFIT_HIT", close_reason=ExitReason.TAKE_PROFIT)
        if time.time() - position.opened_at >= self.config.review_after_seconds and position.unrealized_pnl < 0:
            return ProtectionDecision(ProtectionAction.REVIEW_REQUIRED, "TIME_EXIT_REVIEW_REQUIRED", close_reason=ExitReason.REVIEW_REQUIRED)
        return ProtectionDecision(ProtectionAction.NONE, "HOLD")
