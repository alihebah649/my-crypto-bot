"""Trade Manager facade for the modular Parts 6-8 components.

The facade is the application-facing lifecycle boundary.  Risk approval is
performed before any BUY is submitted, and position state is committed only
after a successful execution outcome.  Spot mode is enforced by the Part-6
risk gateway and the Part-7 execution gateway.
"""
from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional, Tuple
from uuid import uuid4

from .calculator import PositionCalculator
from .controller import PositionController
from .history import PositionHistoryService
from .integration_contracts import (
    ExecutionGateway,
    ExecutionRequest,
    ExecutionSide,
    RiskGateway,
    RiskSizingRequest,
)
from .metrics import PositionMetrics, PositionMetricsService
from .models import Position, PositionCloseReason, PositionSide, PositionStatus
from .repository import PositionRepository
from .risk_manager import PositionExitDecision, PositionExitReason, PositionRiskManager
from .synchronizer import ExchangePositionAdapter, PositionSynchronizer, SynchronizationResult


class PositionManagementFacade:
    """Single application boundary for Trade Manager position lifecycle."""

    def __init__(
        self,
        repository: PositionRepository,
        controller: PositionController,
        calculator: PositionCalculator,
        risk_manager: PositionRiskManager,
        exchange_adapter: Optional[ExchangePositionAdapter] = None,
        execution_gateway: Optional[ExecutionGateway] = None,
        risk_gateway: Optional[RiskGateway] = None,
        risk_approval: Optional[Callable[..., bool]] = None,
    ) -> None:
        self.repository = repository
        self.controller = controller
        self.calculator = calculator
        self.risk_manager = risk_manager
        self.execution_gateway = execution_gateway
        self.risk_gateway = risk_gateway
        # Kept only as a compatibility escape hatch for older callers. New code
        # must use the typed RiskGateway contract.
        self.risk_approval = risk_approval

        if execution_gateway is not None and getattr(controller, "execution_gateway", None) is None:
            controller.execution_gateway = execution_gateway

        self.history_service = PositionHistoryService(calculator)
        self.metrics = PositionMetricsService(self.history_service)
        self.synchronizer = (
            PositionSynchronizer(repository, controller, calculator, exchange_adapter)
            if exchange_adapter is not None
            else None
        )

    def _approve_entry(
        self,
        *,
        symbol: str,
        quantity: float,
        entry_price: float,
        stop_loss: float,
        take_profit: Optional[float],
        account_equity: Optional[float],
        free_balance: Optional[float],
        estimated_fee: float,
    ) -> Tuple[bool, float, Dict[str, Any]]:
        """Return (approved, allowed_quantity, metadata). Fail closed."""
        if self.risk_gateway is not None:
            if account_equity is None or free_balance is None:
                return False, 0.0, {"reason": "ACCOUNT_SNAPSHOT_REQUIRED"}
            approval = self.risk_gateway.approve(
                RiskSizingRequest(
                    symbol=symbol,
                    entry_price=entry_price,
                    stop_loss=stop_loss,
                    account_equity=account_equity,
                    free_balance=free_balance,
                    estimated_fee=estimated_fee,
                    maintenance_margin=0.0,
                    leverage=1.0,
                )
            )
            if not approval.approved:
                return False, 0.0, {"reason": approval.reason, **dict(approval.metadata)}
            allowed_quantity = approval.quantity
            if quantity > 0:
                allowed_quantity = min(quantity, allowed_quantity)
            return allowed_quantity > 0, allowed_quantity, dict(approval.metadata)

        # Legacy callback path. It is intentionally secondary and does not
        # calculate sizing; it only approves/rejects the caller's quantity.
        if self.risk_approval is None:
            return False, 0.0, {"reason": "RISK_GATE_NOT_WIRED"}
        try:
            approved = bool(
                self.risk_approval(
                    symbol=symbol,
                    quantity=quantity,
                    entry_price=entry_price,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                )
            )
        except Exception as exc:
            return False, 0.0, {"reason": "RISK_APPROVAL_ERROR", "error": str(exc)}
        return approved and quantity > 0, quantity, {"source": "LEGACY_CALLBACK"}

    def open_position(
        self,
        symbol: str,
        quantity: float,
        entry_price: float,
        stop_loss: float,
        take_profit: Optional[float] = None,
        entry_metadata: Optional[dict] = None,
        *,
        account_equity: Optional[float] = None,
        free_balance: Optional[float] = None,
        estimated_fee: float = 0.0,
    ) -> Optional[Position]:
        """Open a spot position only after Part-6 approval and Part-7 success."""
        if self.execution_gateway is None:
            return None
        if quantity <= 0 or entry_price <= 0 or stop_loss <= 0 or stop_loss == entry_price:
            return None

        approved, allowed_quantity, risk_metadata = self._approve_entry(
            symbol=symbol,
            quantity=quantity,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            account_equity=account_equity,
            free_balance=free_balance,
            estimated_fee=estimated_fee,
        )
        if not approved:
            return None

        client_order_id = f"CLIENT-{uuid4().hex[:16]}"
        outcome = self.execution_gateway.submit(
            ExecutionRequest(
                symbol=symbol,
                side=ExecutionSide.BUY,
                quantity=allowed_quantity,
                order_type="MARKET",
                client_order_id=client_order_id,
                metadata={"trade_manager_action": "SPOT_OPEN", "risk": risk_metadata},
            )
        )
        if not outcome.success or outcome.executed_quantity <= 0 or outcome.average_price <= 0:
            return None

        position = Position(
            position_id=f"POS-{uuid4().hex[:12]}",
            symbol=symbol,
            side=PositionSide.LONG,
            status=PositionStatus.OPEN,
            quantity=outcome.executed_quantity,
            entry_price=outcome.average_price,
            current_price=outcome.average_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            entry_metadata=dict(entry_metadata or {}),
            client_order_id=client_order_id,
            exchange_order_id=outcome.exchange_order_id,
            entry_fee=outcome.commission,
            total_fees=outcome.commission,
        )
        position.entry_metadata["entry_time"] = time.time()
        position.entry_metadata["execution_source"] = outcome.metadata.get(
            "source", "CORE_EXECUTION_GATEWAY"
        )
        position.entry_metadata["risk_metadata"] = risk_metadata
        self.repository.add(position)
        return position

    def close_position(
        self,
        position_id: str,
        exit_price: float,
        reason: PositionCloseReason = PositionCloseReason.MANUAL,
    ) -> Optional[Position]:
        decision = PositionExitDecision(
            True,
            PositionExitReason.REVIEW_REQUIRED,
            exit_price,
            f"Manual close: {reason.name}",
        )
        position = self.controller.execute_exit_decision(position_id, decision, self.calculator)
        if position and position.status == PositionStatus.CLOSED:
            position.close_reason = reason
            self.repository.update(position)
            self.history_service.record_closed_position(position)
            self.metrics.refresh()
        return position

    def evaluate_all(self) -> List[Tuple[Position, PositionExitDecision]]:
        return self.controller.evaluate_positions()

    def execute_decision(
        self,
        position_id: str,
        decision: PositionExitDecision,
    ) -> Optional[Position]:
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
