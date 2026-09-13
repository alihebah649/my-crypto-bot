from trade_manager.calculator import PositionCalculator
from trade_manager.controller import PositionController
from trade_manager.facade import PositionManagementFacade
from trade_manager.integration_contracts import (
    ExecutionGateway,
    ExecutionOutcome,
    ExecutionOutcomeRecord,
    ExecutionRequest,
    ExecutionSide,
    RiskGateway,
    RiskSizingApproval,
    RiskSizingRequest,
)
from trade_manager.repository import PositionRepository
from trade_manager.risk_manager import PositionExitDecision, PositionExitReason, PositionRiskManager


class _DeterministicRiskGateway(RiskGateway):
    def approve(self, request: RiskSizingRequest) -> RiskSizingApproval:
        return RiskSizingApproval(
            approved=True,
            reason="APPROVED",
            quantity=0.001,
            position_value=0.1,
            capital_required=0.1,
            risk_amount=0.001,
            stop_distance=0.01,
            leverage=1.0,
            metadata={"source": "TEST"},
        )


class _DeterministicExecutionGateway(ExecutionGateway):
    def submit(self, request: ExecutionRequest) -> ExecutionOutcomeRecord:
        price = float(request.price or (100.0 if request.side is ExecutionSide.BUY else 101.0))
        return ExecutionOutcomeRecord(
            success=True,
            outcome=ExecutionOutcome.SUCCESS,
            symbol=request.symbol,
            side=request.side,
            requested_quantity=request.quantity,
            executed_quantity=request.quantity,
            average_price=price,
            exchange_order_id=f"{request.side.value}-RELOAD-1",
            client_order_id=request.client_order_id,
            commission=0.0001,
            message="deterministic test fill",
            metadata={"source": "TEST"},
        )

    def cancel(self, *, symbol, exchange_order_id=None, client_order_id=None):
        return ExecutionOutcomeRecord(
            success=True,
            outcome=ExecutionOutcome.CANCELLED,
            symbol=symbol,
            side=ExecutionSide.SELL,
            requested_quantity=0.0,
            executed_quantity=0.0,
            average_price=0.0,
            exchange_order_id=exchange_order_id,
            client_order_id=client_order_id,
            message="cancelled",
        )

    def close_spot(self, *, symbol, quantity, client_order_id=None, execution_price=None):
        return self.submit(
            ExecutionRequest(
                symbol=symbol,
                side=ExecutionSide.SELL,
                quantity=quantity,
                order_type="MARKET",
                price=execution_price or 101.0,
                client_order_id=client_order_id,
            )
        )


def test_full_closed_lifecycle_persists_and_reloads(tmp_path):
    repository = PositionRepository(persistence_path=str(tmp_path / "positions.json"))
    calculator = PositionCalculator()
    risk_manager = PositionRiskManager()
    execution_gateway = _DeterministicExecutionGateway()
    facade = PositionManagementFacade(
        repository=repository,
        controller=PositionController(risk_manager, repository, execution_gateway),
        calculator=calculator,
        risk_manager=risk_manager,
        execution_gateway=execution_gateway,
        risk_gateway=_DeterministicRiskGateway(),
        persistence_dir=str(tmp_path),
    )

    position = facade.open_position(
        symbol="BTCUSDT",
        quantity=0.001,
        entry_price=100.0,
        stop_loss=99.0,
        take_profit=102.0,
        account_equity=1000.0,
        free_balance=1000.0,
        entry_metadata={"trade_mode": "SCALP"},
    )

    assert position is not None
    position_id = position.position_id

    decision = PositionExitDecision(
        should_exit=True,
        reason=PositionExitReason.TAKE_PROFIT,
        exit_price=101.0,
        message="test take profit",
    )
    closed = facade.execute_decision(position_id, decision)

    assert closed is not None
    assert closed.position_id == position_id
    assert closed.status.name == "CLOSED"
    assert closed.close_reason.name == "TAKE_PROFIT"
    assert closed.metadata["exit_decision_trace"]["execution_outcome"] == "CLOSED"

    reloaded_repository = PositionRepository(persistence_path=str(tmp_path / "positions.json"))
    persisted = reloaded_repository.get(position_id)
    from trade_manager.history import PositionHistoryService
    history = PositionHistoryService(persistence_dir=str(tmp_path)).repository.get_all_records()

    assert persisted is not None
    assert persisted.position_id == position_id
    assert persisted.status.name == "CLOSED"
    assert len(history) == 1
    assert history[0].position_id == position_id
    assert history[0].close_reason == "TAKE_PROFIT"
    assert history[0].realized_pnl == closed.realized_pnl
    assert history[0].total_fees == closed.total_fees
