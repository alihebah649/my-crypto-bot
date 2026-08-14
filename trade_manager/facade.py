"""Trade Manager facade: canonical Part-8 position lifecycle boundary."""
from __future__ import annotations

import time
from typing import Dict, List, Optional, Tuple
from uuid import uuid4

from .calculator import PositionCalculator
from .controller import PositionController
from .history import PositionHistoryService
from .metrics import PositionMetrics, PositionMetricsService
from .models import Position, PositionCloseReason, PositionSide, PositionStatus
from .repository import PositionRepository
from .risk_manager import PositionExitDecision, PositionExitReason, PositionRiskManager
from .risk import RiskEvaluation, RiskManager
from .synchronizer import ExchangePositionAdapter, PositionSynchronizer, SynchronizationResult


class PositionManagementFacade:
    """Single public boundary for Part 8.1-8.8.

    Entry risk (Part 6) is exposed through ``validate_entry``. Open-position
    recovery/exit logic (8.4) remains in ``PositionRiskManager`` and execution
    remains behind the Part-7 ``ExecutionPipeline`` supplied by the caller.
    """

    def __init__(self, repository: PositionRepository, controller: PositionController,
                 calculator: PositionCalculator, risk_manager: PositionRiskManager,
                 entry_risk_manager: Optional[RiskManager] = None,
                 exchange_adapter: Optional[ExchangePositionAdapter] = None):
        self.repository = repository
        self.controller = controller
        self.calculator = calculator
        self.risk_manager = risk_manager
        self.entry_risk_manager = entry_risk_manager or RiskManager()
        self.history_service = PositionHistoryService(calculator)
        self.metrics = PositionMetricsService(self.history_service)
        self.synchronizer = (PositionSynchronizer(repository, controller, calculator, exchange_adapter)
                             if exchange_adapter else None)

    def validate_entry(self, *, equity: float, free_balance: float, entry_price: float,
                       stop_loss: float, current_exposure: float = 0.0,
                       symbol_exposure: float = 0.0, spread_percent: float = 0.0,
                       slippage_percent: float = 0.0, estimated_fee: float = 0.0) -> RiskEvaluation:
        """Part-6 -> Part-8 entry gate. No position is created on rejection."""
        return self.entry_risk_manager.evaluate(
            equity=equity,
            free_balance=free_balance,
            entry_price=entry_price,
            stop_loss=stop_loss,
            open_positions=len(self.repository.get_open_positions()),
            current_exposure=current_exposure,
            symbol_exposure=symbol_exposure,
            spread_percent=spread_percent,
            slippage_percent=slippage_percent,
            estimated_fee=estimated_fee,
        )

    def open_position(self, symbol: str, quantity: float, entry_price: float,
                      stop_loss: float, take_profit: Optional[float] = None,
                      entry_metadata: Optional[dict] = None,
                      *, risk_evaluation: Optional[RiskEvaluation] = None) -> Position:
        """Create a local position after the caller has passed the entry risk gate."""
        if risk_evaluation is not None and not risk_evaluation.approved:
            raise ValueError(f"ENTRY_RISK_REJECTED:{risk_evaluation.reason}")
        if self.repository.get_by_symbol(symbol):
            raise ValueError(f"Position already exists for {symbol}")
        if quantity <= 0 or entry_price <= 0:
            raise ValueError("quantity and entry_price must be positive")
        if stop_loss <= 0 or stop_loss >= entry_price:
            raise ValueError("spot stop_loss must be positive and below entry_price")

        position = Position(
            position_id=f"POS-{uuid4().hex[:12]}",
            symbol=symbol.upper(),
            side=PositionSide.LONG,
            status=PositionStatus.OPEN,
            quantity=quantity,
            entry_price=entry_price,
            current_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            entry_metadata=dict(entry_metadata or {}),
            client_order_id=f"CLIENT-{uuid4().hex[:8]}",
        )
        position.entry_metadata["entry_time"] = time.time()
        self.repository.add(position)
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

    def synchronize(self) -> Optional[SynchronizationResult]:
        return self.synchronizer.synchronize() if self.synchronizer else None

    def get_hold_statistics(self) -> Dict:
        return self.risk_manager.get_hold_statistics()
