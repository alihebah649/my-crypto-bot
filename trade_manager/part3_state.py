"""Trade Manager Part 3 state mutation boundary.

Decisions are produced by the pure Part-2 evaluator and applied here.
No broker/network calls are made in this layer.
"""
from __future__ import annotations
from .protection_models import Trade, TradeDecision, TradeAction
from .protection import ProtectionLogicEvaluator

class TradeStateManager:
    def __init__(self, evaluator: ProtectionLogicEvaluator | None = None):
        self.evaluator = evaluator or ProtectionLogicEvaluator()

    def process_price_update(self, trade: Trade, current_price: float, **rules) -> TradeDecision:
        decision = self.evaluator.evaluate_trade_protection(
            trade=trade, current_price=current_price, **rules
        )
        self.apply_decision(trade, decision)
        return decision

    @staticmethod
    def apply_decision(trade: Trade, decision: TradeDecision) -> None:
        if decision.update_highest and decision.new_highest is not None:
            trade.highest_price = decision.new_highest
        if decision.update_lowest and decision.new_lowest is not None:
            trade.lowest_price = decision.new_lowest
        if decision.activate_trailing:
            trade.trailing_active = True
        if decision.break_even_done:
            trade.break_even_done = True
        if decision.stop_loss is not None and decision.action in {
            TradeAction.UPDATE_STOP, TradeAction.ACTIVATE_BREAK_EVEN
        }:
            trade.stop_loss = decision.stop_loss
        if decision.action in {TradeAction.CLOSE, TradeAction.STOP_LOSS}:
            trade.status = trade.status.__class__.CLOSED
