from trade_manager.calculator import PositionCalculator
from trade_manager.controller import PositionController
from trade_manager.facade import PositionManagementFacade
from trade_manager.history import PositionHistoryRepository, PositionHistoryService
from trade_manager.integration_contracts import (
    ExecutionOutcome,
    ExecutionOutcomeRecord,
    ExecutionRequest,
    ExecutionSide,
    RiskSizingApproval,
)
from trade_manager.models import PositionCloseReason, PositionStatus
from trade_manager.repository import PositionRepository
from trade_manager.risk_manager import (
    PositionExitDecision,
    PositionExitReason,
    PositionRiskManager,
)


class _RiskGateway:
    def approve(self, request):
        return RiskSizingApproval(
            approved=True,
            reason="APPROVED",
            quantity=1.0,
            position_value=request.entry_price,
            capital_required=request.entry_price,
            risk_amount=request.entry_price - request.stop_loss,
            stop_distance=request.entry_price - request.stop_loss,
            metadata={"source": "TEST"},
        )


class _ExecutionGateway:
    def submit(self, request: ExecutionRequest):
        return ExecutionOutcomeRecord(
            success=True,
            outcome=ExecutionOutcome.SUCCESS,
            symbol=request.symbol,
            side=ExecutionSide.BUY,
            requested_quantity=request.quantity,
            executed_quantity=request.quantity,
            average_price=100.0,
            exchange_order_id="BUY-1",
            client_order_id=request.client_order_id,
            commission=0.10,
            metadata={"source": "TEST"},
        )

    def close_spot(self, *, symbol, quantity, client_order_id=None, execution_price=None):
        return ExecutionOutcomeRecord(
            success=True,
            outcome=ExecutionOutcome.SUCCESS,
            symbol=symbol,
            side=ExecutionSide.SELL,
            requested_quantity=quantity,
            executed_quantity=quantity,
            average_price=102.0,
            exchange_order_id="SELL-1",
            client_order_id=client_order_id,
            commission=0.102,
            metadata={"paper_cash_after": 1001.798},
        )

    def cancel(self, **kwargs):
        raise AssertionError("cancel must not be called")


def test_closed_trade_trace_survives_full_reload(tmp_path):
    persistence_dir = tmp_path / "paper"
    persistence_dir.mkdir()
    position_path = persistence_dir / "positions.json"
    history_path = persistence_dir / "position_history.json"

    repository = PositionRepository(persistence_path=str(position_path))
    calculator = PositionCalculator()
    risk_manager = PositionRiskManager()
    execution = _ExecutionGateway()
    history = PositionHistoryService(
        repository=PositionHistoryRepository(path=str(history_path))
    )
    controller = PositionController(risk_manager, repository, execution)
    facade = PositionManagementFacade(
        repository=repository,
        controller=controller,
        calculator=calculator,
        risk_manager=risk_manager,
        execution_gateway=execution,
        risk_gateway=_RiskGateway(),
        persistence_dir=str(persistence_dir),
        history_service=history,
    )

    position = facade.open_position(
        symbol="OPUSDT",
        quantity=1.0,
        entry_price=100.0,
        stop_loss=99.0,
        entry_metadata={"trade_mode": "SCALP", "entry_context": {"score": 77}},
        account_equity=1000.0,
        free_balance=1000.0,
    )
    assert position is not None
    position.entry_context = {
        "schema_version": "entry-context-v1",
        "score": 77,
        "trade_mode": "SCALP",
        "reasons": ["CONFIRMED_5M_REVERSAL"],
    }
    repository.update(position)

    closed = facade.execute_decision(
        position.position_id,
        PositionExitDecision(
            should_exit=True,
            reason=PositionExitReason.TAKE_PROFIT,
            exit_price=102.0,
            message="take profit",
        ),
    )

    assert closed is not None
    assert closed.status is PositionStatus.CLOSED
    assert closed.close_reason is PositionCloseReason.TAKE_PROFIT
    assert closed.realized_pnl == 1.798
    assert closed.exit_metadata["exit_price"] == 102.0
    assert closed.metadata["exit_decision_trace"]["execution_outcome"] == "CLOSED"
    assert closed.metadata["exit_decision_trace"]["realized_pnl"] == 1.798

    reloaded_positions = PositionRepository(persistence_path=str(position_path))
    persisted = reloaded_positions.get(closed.position_id)
    assert persisted is not None
    assert persisted.status is PositionStatus.CLOSED
    assert persisted.entry_context["score"] == 77
    assert persisted.metadata["exit_decision_trace"]["execution_outcome"] == "CLOSED"
    assert persisted.realized_pnl == 1.798

    reloaded_history = PositionHistoryService(
        repository=PositionHistoryRepository(path=str(history_path))
    )
    archived = reloaded_history.get_all_closed_positions()
    assert len(archived) == 1
    archived_position = archived[0]
    assert archived_position.position_id == closed.position_id
    assert archived_position.entry_context["score"] == 77
    assert archived_position.entry_metadata["entry_context"]["score"] == 77
    assert archived_position.exit_metadata["exit_price"] == 102.0
    assert archived_position.metadata["exit_decision_trace"]["realized_pnl"] == 1.798
    assert archived_position.realized_pnl == 1.798
    assert history_path.exists()
