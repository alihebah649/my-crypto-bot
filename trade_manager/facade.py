"""Trade Manager facade for the current modular Part 8 components."""
from typing import Dict, List, Optional, Tuple
from uuid import uuid4
import time
from .calculator import PositionCalculator
from .controller import PositionController
from .history import PositionHistoryService
from .metrics import PositionMetrics, PositionMetricsService
from .models import Position, PositionCloseReason, PositionSide, PositionStatus
from .repository import PositionRepository
from .risk_manager import PositionExitDecision, PositionExitReason, PositionRiskManager
from .synchronizer import ExchangePositionAdapter, PositionSynchronizer, SynchronizationResult


class PositionManagementFacade:
    def __init__(self, repository: PositionRepository, controller: PositionController,
                 calculator: PositionCalculator, risk_manager: PositionRiskManager,
                 exchange_adapter: Optional[ExchangePositionAdapter] = None):
        self.repository = repository
        self.controller = controller
        self.calculator = calculator
        self.risk_manager = risk_manager
        self.history_service = PositionHistoryService(calculator)
        self.metrics = PositionMetricsService(self.history_service)
        self.synchronizer = (PositionSynchronizer(repository, controller, calculator, exchange_adapter)
                             if exchange_adapter else None)

    def open_position(self, symbol: str, quantity: float, entry_price: float,
                      stop_loss: float, take_profit: Optional[float] = None,
                      entry_metadata: Optional[dict] = None) -> Position:
        position = Position(position_id=f"POS-{uuid4().hex[:12]}", symbol=symbol,
                            side=PositionSide.LONG, status=PositionStatus.OPEN,
                            quantity=quantity, entry_price=entry_price, current_price=entry_price,
                            stop_loss=stop_loss, take_profit=take_profit,
                            entry_metadata=dict(entry_metadata or {}),
                            client_order_id=f"CLIENT-{uuid4().hex[:8]}")
        position.entry_metadata["entry_time"] = time.time()
        self.repository.add(position)
        return position

    def close_position(self, position_id: str, exit_price: float,
                       reason: PositionCloseReason = PositionCloseReason.MANUAL) -> Optional[Position]:
        decision = PositionExitDecision(True, PositionExitReason.REVIEW_REQUIRED,
                                        exit_price, f"Manual close: {reason.name}")
        position = self.controller.execute_exit_decision(position_id, decision, self.calculator)
        if position:
            position.close_reason = reason
            self.repository.update(position)
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

    def get_open_positions(self) -> List[Position]: return self.repository.get_open_positions()
    def get_hold_positions(self) -> List[Position]: return self.repository.get_hold_positions()
    def get_review_required(self) -> List[Position]: return self.repository.get_review_required()
    def refresh_metrics(self) -> None: self.metrics.refresh()
    def get_metrics(self) -> PositionMetrics:
        self.metrics.refresh(); return self.metrics.get_metrics()
    def synchronize(self) -> Optional[SynchronizationResult]:
        return self.synchronizer.synchronize() if self.synchronizer else None
    def get_hold_statistics(self) -> Dict: return self.risk_manager.get_hold_statistics()
