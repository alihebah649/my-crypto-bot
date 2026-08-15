"""8.5 - Position lifecycle controller.

A position is never marked CLOSED before the Part-7 execution boundary
confirms a full sell. This prevents local/exchange state divergence.
"""
from __future__ import annotations

import threading
import time
from typing import List, Optional, Tuple

from .calculator import PositionCalculator
from .execution import ExecutionOrder, ExecutionPipeline, ExecutionResult, OrderSide
from .models import Position, PositionCloseReason, PositionStatus
from .repository import PositionRepository
from .risk_manager import PositionExitDecision, PositionExitReason, PositionRiskManager


class PositionController:
    def __init__(self, risk_manager: PositionRiskManager, repository: PositionRepository,
                 execution_pipeline: Optional[ExecutionPipeline] = None):
        self.repository = repository
        self._risk_manager = risk_manager
        self.execution_pipeline = execution_pipeline
        self._lock = threading.RLock()

    def add_position(self, position: Position) -> None:
        with self._lock:
            self.repository.add(position)

    def update_position(self, position: Position) -> None:
        with self._lock:
            self.repository.update(position)

    def get_position(self, position_id: str) -> Optional[Position]:
        return self.repository.get(position_id)

    def get_all_positions(self) -> List[Position]:
        return self.repository.get_all()

    def update_market_price(self, symbol: str, current_price: float) -> None:
        if current_price <= 0:
            raise ValueError("current_price must be positive")
        with self._lock:
            for position in self.repository.get_by_symbol(symbol):
                if position.status in {PositionStatus.OPEN, PositionStatus.HOLD, PositionStatus.REVIEW_REQUIRED}:
                    position.current_price = current_price
                    position.update_highest_price(current_price)
                    position.update_lowest_price(current_price)
                    position.update_max_profit(current_price)
                    position.update_max_drawdown(current_price)
                    self.repository.update(position)

    def evaluate_positions(self) -> List[Tuple[Position, PositionExitDecision]]:
        decisions = []
        with self._lock:
            for position in self.repository.get_open_positions():
                if position.status in {PositionStatus.OPEN, PositionStatus.HOLD}:
                    decisions.append((position, self._risk_manager.evaluate(position)))
        return decisions

    def _execute_exit(self, position: Position, exit_price: float) -> Optional[ExecutionResult]:
        if self.execution_pipeline is None:
            return None
        order = ExecutionOrder(symbol=position.symbol, side=OrderSide.SELL,
                               quantity=position.quantity, price=exit_price)
        return self.execution_pipeline.execute(order)

    def execute_exit_decision(self, position_id: str, decision: PositionExitDecision,
                              calculator: PositionCalculator) -> Optional[Position]:
        with self._lock:
            position = self.repository.get(position_id)
            if not position:
                return None
            if decision.review_required:
                position.status = PositionStatus.REVIEW_REQUIRED
                position.review_required_at = time.time()
                self.repository.update(position)
                return position
            if not decision.should_exit:
                return position
            if position.status not in {PositionStatus.OPEN, PositionStatus.HOLD, PositionStatus.REVIEW_REQUIRED}:
                return None
            if decision.exit_price <= 0:
                raise ValueError("exit_price must be positive")

            execution = self._execute_exit(position, decision.exit_price)
            if execution is not None:
                if not execution.success:
                    position.metadata["last_exit_execution_error"] = execution.message
                    self.repository.update(position)
                    return position
                if execution.executed_quantity + 1e-12 < position.quantity:
                    position.quantity = max(0.0, position.quantity - execution.executed_quantity)
                    position.status = PositionStatus.PARTIALLY_CLOSED
                    position.current_price = execution.average_price or decision.exit_price
                    position.metadata["partial_exit"] = {
                        "executed_quantity": execution.executed_quantity,
                        "remaining_quantity": position.quantity,
                        "exchange_order_id": execution.exchange_order_id,
                    }
                    self.repository.update(position)
                    return position
                exit_price = execution.average_price or decision.exit_price
            else:
                exit_price = decision.exit_price

            # Lifecycle mutation occurs only after a successful full execution.
            position.status = PositionStatus.CLOSED
            position.closed_at = time.time()
            position.current_price = exit_price
            reason_map = {
                PositionExitReason.STOP_LOSS: PositionCloseReason.STOP_LOSS,
                PositionExitReason.TAKE_PROFIT: PositionCloseReason.TAKE_PROFIT,
                PositionExitReason.TRAILING_STOP: PositionCloseReason.TRAILING_STOP,
                PositionExitReason.BREAK_EVEN: PositionCloseReason.BREAK_EVEN,
                PositionExitReason.MANUAL: PositionCloseReason.MANUAL,
                PositionExitReason.REVIEW_REQUIRED: PositionCloseReason.REVIEW_EXIT,
                PositionExitReason.RECOVERY_FAILED: PositionCloseReason.RECOVERY_FAILED,
            }
            position.close_reason = reason_map.get(decision.reason, PositionCloseReason.MANUAL)
            result = calculator.calculate(position, exit_price)
            position.gross_pnl = result.gross_pnl
            position.realized_pnl = result.net_pnl
            position.total_fees = result.total_fees
            position.entry_fee = result.entry_fee
            position.exit_fee = result.exit_fee
            position.exit_metadata = {
                "exit_price": exit_price,
                "exit_reason": decision.reason.name,
                "exit_message": decision.message,
                "exit_time": time.time(),
                "max_profit_percent": position.max_profit_percent,
                "max_drawdown_percent": position.max_drawdown_percent,
                "execution_order_id": getattr(execution, "exchange_order_id", None),
            }
            self.repository.update(position)
            return position

    def execute_review_decision(self, position_id: str, should_exit: bool,
                                calculator: PositionCalculator) -> Optional[Position]:
        with self._lock:
            position = self.repository.get(position_id)
            if not position or position.status != PositionStatus.REVIEW_REQUIRED:
                return None
            if should_exit:
                decision = PositionExitDecision(True, PositionExitReason.REVIEW_REQUIRED,
                                                position.current_price, "Exit after review")
                return self.execute_exit_decision(position_id, decision, calculator)
            position.status = PositionStatus.HOLD
            position.entered_hold_at = time.time()
            position.review_required_at = None
            self.repository.update(position)
            return position

    def has_position(self, symbol: str) -> bool:
        return any(p.symbol == symbol and p.status in {
            PositionStatus.OPEN, PositionStatus.HOLD, PositionStatus.REVIEW_REQUIRED,
            PositionStatus.PARTIALLY_CLOSED
        } for p in self.repository.get_by_symbol(symbol))

    def get_symbol_positions(self, symbol: str) -> List[Position]:
        return self.repository.get_by_symbol(symbol)

    def clear(self) -> None:
        self.repository.clear()
