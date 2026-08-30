"""8.5 - Position lifecycle controller.

State mutation is deliberately downstream of execution. A rejected/failed
execution never marks a Position CLOSED.
"""
from __future__ import annotations
import threading
import time
from typing import List, Optional, Tuple
from .calculator import PositionCalculator
from .integration_contracts import ExecutionGateway
from .models import Position, PositionCloseReason, PositionStatus
from .repository import PositionRepository
from .risk_manager import PositionExitDecision, PositionExitReason, PositionRiskManager


class PositionController:
    def __init__(self, risk_manager: PositionRiskManager, repository: PositionRepository,
                 execution_gateway: Optional[ExecutionGateway] = None,
                 history_service=None):
        self.repository = repository
        self._risk_manager = risk_manager
        self.execution_gateway = execution_gateway
        self.history_service = history_service
        self._lock = threading.RLock()

    def add_position(self, position: Position) -> None:
        with self._lock: self.repository.add(position)
    def update_position(self, position: Position) -> None:
        with self._lock: self.repository.update(position)
    def get_position(self, position_id: str) -> Optional[Position]: return self.repository.get(position_id)
    def get_all_positions(self) -> List[Position]: return self.repository.get_all()

    def update_market_price(self, symbol: str, current_price: float) -> None:
        if current_price<=0: raise ValueError("current_price must be positive")
        with self._lock:
            for position in self.repository.get_by_symbol(symbol):
                if position.status in {PositionStatus.OPEN,PositionStatus.HOLD,PositionStatus.REVIEW_REQUIRED}:
                    position.current_price=current_price;position.update_highest_price(current_price)
                    position.update_lowest_price(current_price);position.update_max_profit(current_price)
                    position.update_max_drawdown(current_price);self.repository.update(position)

    def evaluate_positions(self)->List[Tuple[Position,PositionExitDecision]]:
        decisions=[]
        with self._lock:
            for position in self.repository.get_open_positions():
                if position.status in {PositionStatus.OPEN,PositionStatus.HOLD}:
                    decisions.append((position,self._risk_manager.evaluate(position)))
        return decisions

    def execute_exit_decision(self, position_id: str, decision: PositionExitDecision,
                              calculator: PositionCalculator) -> Optional[Position]:
        with self._lock:
            position=self.repository.get(position_id)
            if not position:return None
            if decision.review_required:
                position.status=PositionStatus.REVIEW_REQUIRED;position.review_required_at=time.time();self.repository.update(position);return position
            if not decision.should_exit:return position
            if position.status not in {PositionStatus.OPEN,PositionStatus.HOLD,PositionStatus.REVIEW_REQUIRED}:return None
            if self.execution_gateway is None:
                # Fail closed: local state must never claim a sale that was not executed.
                return None

            # A fee-aware Break-Even is a net-protection floor, not merely a
            # price-above-entry trigger. Never submit a BE exit while the
            # requested execution price is below the calculated round-trip
            # fee-adjusted break-even price.
            if decision.reason is PositionExitReason.BREAK_EVEN:
                break_even_price = calculator.break_even_price(position)
                requested_exit_price = decision.exit_price if decision.exit_price > 0 else position.current_price
                if requested_exit_price < break_even_price:
                    return position

            outcome=self.execution_gateway.close_spot(symbol=position.symbol,quantity=position.quantity,client_order_id=position.client_order_id)
            if not outcome.success or outcome.executed_quantity<=0 or outcome.average_price<=0:
                return None
            executed_qty=min(position.quantity,outcome.executed_quantity)
            exit_price=outcome.average_price
            # Some lightweight test/integration gateways predate the optional
            # outcome metadata field. Treat missing metadata as empty metadata;
            # the execution itself remains authoritative for closing the trade.
            outcome_metadata = getattr(outcome, "metadata", {}) or {}
            if executed_qty < position.quantity:
                # Preserve the remaining owned asset as an active spot position.
                original_qty=position.quantity
                position.quantity=original_qty-executed_qty
                position.current_price=exit_price
                position.exit_fee += outcome.commission
                position.total_fees += outcome.commission
                position.exit_metadata={"partial_exit_quantity":executed_qty,"partial_exit_price":exit_price,
                                        "partial_exit_time":time.time(),"execution_order_id":outcome.exchange_order_id}
                if "paper_cash_after" in outcome_metadata:
                    position.exit_metadata["paper_cash_after"] = float(outcome_metadata["paper_cash_after"])
                position.status=PositionStatus.OPEN
                self.repository.update(position)
                return position
            position.status=PositionStatus.CLOSED;position.closed_at=time.time();position.current_price=exit_price
            reason_map={PositionExitReason.STOP_LOSS:PositionCloseReason.STOP_LOSS,PositionExitReason.TAKE_PROFIT:PositionCloseReason.TAKE_PROFIT,
                        PositionExitReason.TRAILING_STOP:PositionCloseReason.TRAILING_STOP,PositionExitReason.BREAK_EVEN:PositionCloseReason.BREAK_EVEN,
                        PositionExitReason.REVIEW_REQUIRED:PositionCloseReason.REVIEW_EXIT,PositionExitReason.RECOVERY_FAILED:PositionCloseReason.RECOVERY_FAILED}
            position.close_reason=reason_map.get(decision.reason,PositionCloseReason.MANUAL)
            result=calculator.calculate(position,exit_price)
            position.gross_pnl=result.gross_pnl
            position.entry_fee=result.entry_fee
            position.exit_fee=outcome.commission if outcome.commission>0 else result.exit_fee
            position.total_fees=position.entry_fee+position.exit_fee
            position.realized_pnl=position.gross_pnl-position.total_fees
            position.exit_metadata={"exit_price":exit_price,"exit_reason":decision.reason.name,"exit_message":decision.message,
                                    "exit_time":time.time(),"exchange_order_id":outcome.exchange_order_id,
                                    "executed_quantity":outcome.executed_quantity,"commission":outcome.commission,
                                    "max_profit_percent":position.max_profit_percent,"max_drawdown_percent":position.max_drawdown_percent}
            if "paper_cash_after" in outcome_metadata:
                position.exit_metadata["paper_cash_after"] = float(outcome_metadata["paper_cash_after"])
            self.repository.update(position)
            if self.history_service is not None:
                self.history_service.record_closed_position(position)
            return position

    def execute_review_decision(self, position_id: str, should_exit: bool,
                                calculator: PositionCalculator) -> Optional[Position]:
        with self._lock:
            position=self.repository.get(position_id)
            if not position or position.status!=PositionStatus.REVIEW_REQUIRED:return None
            if should_exit:
                decision=PositionExitDecision(True,PositionExitReason.REVIEW_REQUIRED,position.current_price,"Exit after review")
                return self.execute_exit_decision(position_id,decision,calculator)
            position.status=PositionStatus.HOLD;position.entered_hold_at=time.time();position.review_required_at=None
            self.repository.update(position);return position

    def has_position(self,symbol:str)->bool:
        return any(p.symbol==symbol and p.status in {PositionStatus.OPEN,PositionStatus.HOLD,PositionStatus.REVIEW_REQUIRED} for p in self.repository.get_by_symbol(symbol))
    def get_symbol_positions(self,symbol:str)->List[Position]: return self.repository.get_by_symbol(symbol)
    def clear(self)->None:self.repository.clear()
