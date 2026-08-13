"""State mutation layer from Trade Manager Part 2."""

from __future__ import annotations

from typing import Optional

from .protection import ProtectionLogicEvaluator
from .protection_models import Trade, TradeAction, TradeDecision


class TradeStateMutator:
    """Apply pure protection decisions to a trade object."""

    def __init__(self, evaluator: Optional[ProtectionLogicEvaluator] = None) -> None:
        self.evaluator = evaluator or ProtectionLogicEvaluator()

    def process_price_update(
        self,
        trade: Trade,
        current_price: float,
        break_even_trigger: float = 0.02,
        trailing_activation: float = 0.03,
        trailing_distance: float = 0.01,
        fees_buffer: float = 0.0,
    ) -> TradeDecision:
        decision = self.evaluator.evaluate_trade_protection(
            trade=trade,
            current_price=current_price,
            break_even_trigger=break_even_trigger,
            trailing_activation=trailing_activation,
            trailing_distance=trailing_distance,
            fees_buffer=fees_buffer,
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

        if decision.break_even_done is True:
            trade.break_even_done = True

        if decision.stop_loss is not None and decision.action in (
            TradeAction.UPDATE_STOP,
            TradeAction.ACTIVATE_BREAK_EVEN,
        ):
            trade.stop_loss = decision.stop_loss

        if decision.action in (TradeAction.CLOSE, TradeAction.STOP_LOSS):
            trade.status = trade.status.__class__.CLOSED
