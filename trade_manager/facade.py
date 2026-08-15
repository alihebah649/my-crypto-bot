"""Trade Manager facade: canonical Part-8.1-8.8 lifecycle boundary."""
from __future__ import annotations

import time
from typing import Dict, List, Optional, Tuple
from uuid import uuid4

from .calculator import PositionCalculator
from .controller import PositionController
from .execution import ExecutionOrder, ExecutionPipeline, ExecutionResult, OrderSide
from .history import PositionHistoryService
from .metrics import PositionMetrics, PositionMetricsService
from .models import Position, PositionCloseReason, PositionSide, PositionStatus
from .repository import PositionRepository
from .risk_manager import PositionExitDecision, PositionExitReason, PositionRiskManager
from .risk import RiskEvaluation, RiskManager
from .synchronizer import ExchangePositionAdapter, PositionSynchronizer


class PositionManagementFacade:
    """Single public boundary for Part 8.1-8.8.

    Part 6 validates new entries. Part 7 executes orders. Part 8 owns the
    canonical position lifecycle and P&L/history state.
    """

    def __init__(self, repository: PositionRepository, controller: PositionController,
                 calculator: PositionCalculator, risk_manager: PositionRiskManager,
                 entry_risk_manager: Optional[RiskManager] = None,
                 exchange_adapter: Optional[ExchangePositionAdapter] = None,
                 execution_pipeline: Optional[ExecutionPipeline] = None):
        self.repository = repository
        self.controller = controller
        self.calculator = calculator
        self.risk_manager = risk_manager
        self.entry_risk_manager = entry_risk_manager or RiskManager()
        self.history_service = PositionHistoryService(calculator)
        self.metrics = PositionMetricsService(self.history_service)
        self.synchronizer = (PositionSynchronizer(repository, controller, calculator, exchange_adapter)
                             if exchange_adapter else None)
        if execution_pipeline is not None:
            self.controller.execution_pipeline = execution_pipeline

    def validate_entry(self, *, equity: float, free_balance: float, entry_price: float,
                       stop_loss: float, current_exposure: float = 0.0,
                       symbol_exposure: float = 0.0, spread_percent: float = 0.0,
                       slippage_percent: float = 0.0, estimated_fee: float = 0.0) -> RiskEvaluation:
        return self.entry_risk_manager.evaluate(
            equity=equity, free_balance=free_balance, entry_price=entry_price,
            stop_loss=stop_loss, open_positions=len(self.repository.get_open_positions()),
            current_exposure=current_exposure, symbol_exposure=symbol_exposure,
            spread_percent=spread_percent, slippage_percent=slippage_percent,
            estimated_fee=estimated_fee,
        )

    def open_position_with_execution(self, symbol: str, quantity: float, entry_price: float,
                                     stop_loss: float, take_profit: Optional[float] = None,
                                     entry_metadata: Optional[dict] = None,
                                     *, risk_evaluation: Optional[RiskEvaluation] = None
                                     ) -> Tuple[Optional[Position], ExecutionResult]:
        if risk_evaluation is not None and not risk_evaluation.approved:
            return None, ExecutionResult(False, symbol, "BUY", quantity,
                                         message=f"ENTRY_RISK_REJECTED:{risk_evaluation.reason}")
        if self.controller.has_position(symbol):
            return None, ExecutionResult(False, symbol, "BUY", quantity,
                                         message=f"POSITION_ALREADY_EXISTS:{symbol}")
        if quantity <= 0 or entry_price <= 0:
            return None, ExecutionResult(False, symbol, "BUY", quantity, message="INVALID_ENTRY")
        if stop_loss <= 0 or stop_loss >= entry_price:
            return None, ExecutionResult(False, symbol, "BUY", quantity, message="INVALID_SPOT_STOP")
        if self.controller.execution_pipeline is None:
            raise RuntimeError("Part-7 execution pipeline is not configured")

        order = ExecutionOrder(symbol=symbol.upper(), side=OrderSide.BUY,
                               quantity=quantity, price=entry_price)
        execution = self.controller.execution_pipeline.execute(order)
        if not execution.success:
            return None, execution

        filled_qty = execution.executed_quantity or quantity
        filled_price = execution.average_price or entry_price
        position = Position(
            position_id=f"POS-{uuid4().hex[:12]}", symbol=symbol.upper(),
            side=PositionSide.LONG, status=PositionStatus.OPEN,
            quantity=filled_qty, entry_price=filled_price, current_price=filled_price,
            stop_loss=stop_loss, take_profit=take_profit,
            entry_metadata=dict(entry_metadata or {}),
            exchange_order_id=execution.exchange_order_id,
            client_order_id=execution.client_order_id,
            entry_fee=execution.commission,
            total_fees=execution.commission,
        )
        position.entry_metadata["entry_time"] = time.time()
        self.repository.add(position)
        return position, execution

    def open_position(self, symbol: str, quantity: float, entry_price: float,
                      stop_loss: float, take_profit: Optional[float] = None,
                      entry_metadata: Optional[dict] = None,
                      *, risk_evaluation: Optional[RiskEvaluation] = None) -> Position:
        position, execution = self.open_position_with_execution(
            symbol, quantity, entry_price, stop_loss, take_profit, entry_metadata,
            risk_evaluation=risk_evaluation,
        )
        if position is None:
            raise ValueError(execution.message or "ENTRY_EXECUTION_FAILED")
        return position

    def close_position(self, position_id: str, exit_price: float,
                       reason: PositionCloseReason = PositionCloseReason.MANUAL) -> Optional[Position]:
        decision_reason = {
            PositionCloseReason.STOP_LOSS: PositionExitReason.STOP_LOSS,
            PositionCloseReason.TAKE_PROFIT: PositionExitReason.TAKE_PROFIT,
            PositionCloseReason.TRAILING_STOP: PositionExitReason.TRAILING_STOP,
            PositionCloseReason.BREAK_EVEN: PositionExitReason.BREAK_EVEN,
            PositionCloseReason.RECOVERY_FAILED: PositionExitReason.RECOVERY_FAILED,
            PositionCloseReason.REVIEW_EXIT: PositionExitReason.REVIEW_REQUIRED,
        }.get(reason, PositionExitReason.MANUAL)
        decision = PositionExitDecision(True, decision_reason, exit_price,
                                        f"Close requested: {reason.name}")
        position = self.controller.execute_exit_decision(position_id, decision, self.calculator)
        if position and position.status == PositionStatus.CLOSED:
            self.history_service.record_closed_position(position)
            self.metrics.refresh()
        return position

    def evaluate_all(self) -> List[Tuple[Position, PositionExitDecision]]:
        return self.controller.evaluate_positions()

    def execute_decision(self, position_id: str, decision: PositionExitDecision) -> Optional[Position]:
        position = self.controller.execute_exit_decision(position_id, decision, self.calculator)
        if position and position.status == PositionStatus.CLOSED:
            self.history_service.record_closed_position(position)
            self.metrics.refresh()
        return position

    def archive_closed_position(self, position_id: str) -> Optional[Position]:
        position = self.repository.get(position_id)
        if not position or position.status != PositionStatus.CLOSED:
            return None
        self.history_service.record_closed_position(position)
        self.metrics.refresh()
        return position

    def get_open_positions(self) -> List[Position]:
        return self.repository.get_open_positions()

    def get_hold_positions(self) -> List[Position]:
        return self.repository.get_hold_positions()

    def get_review_required(self) -> List[Position]:
        return self.repository.get_review_required()

    def refresh_metrics(self) -> None:
        self.metrics.refresh()

    def get_metrics(self) -> PositionMetrics:
        self.metrics.refresh()
        return self.metrics.get_metrics()

    def synchronize(self):
        return self.synchronizer.synchronize() if self.synchronizer else None

    def get_hold_statistics(self) -> Dict:
        return self.risk_manager.get_hold_statistics()
