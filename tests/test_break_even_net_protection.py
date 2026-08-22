"""Regression tests for fee-aware Break-Even net-profit protection."""

from types import SimpleNamespace

from trade_manager.calculator import PositionCalculator
from trade_manager.controller import PositionController
from trade_manager.integration_contracts import ExecutionOutcome
from trade_manager.models import Position, PositionSide, PositionStatus
from trade_manager.repository import PositionRepository
from trade_manager.risk_manager import PositionExitDecision, PositionExitReason, PositionRiskManager


class _PaperCloseGateway:
    def __init__(self, executed_price: float) -> None:
        self.executed_price = executed_price

    def close_spot(self, *, symbol: str, quantity: float, client_order_id=None):
        return SimpleNamespace(
            success=True,
            outcome=ExecutionOutcome.SUCCESS,
            executed_quantity=quantity,
            average_price=self.executed_price,
            exchange_order_id="BE-REGRESSION-SELL",
            commission=quantity * self.executed_price * 0.001,
        )

    def submit(self, request):
        raise AssertionError("submit() is not part of this regression")

    def cancel(self, **kwargs):
        raise AssertionError("cancel() is not part of this regression")


def _position(current_price: float) -> Position:
    return Position(
        position_id="BE-REGRESSION",
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        status=PositionStatus.OPEN,
        quantity=1.0,
        entry_price=100.0,
        current_price=current_price,
        stop_loss=100.2002002002,
        take_profit=None,
        metadata={"break_even_activated": True},
    )


def _break_even_decision(position: Position) -> PositionExitDecision:
    return PositionExitDecision(
        should_exit=True,
        reason=PositionExitReason.BREAK_EVEN,
        exit_price=position.current_price,
        message="Break-Even protection triggered",
    )


def test_break_even_must_not_close_below_fee_aware_net_break_even():
    """A BE exit must not close the position at a price below fee-aware BE."""
    position = _position(100.10)
    repository = PositionRepository()
    gateway = _PaperCloseGateway(executed_price=100.10)
    controller = PositionController(
        risk_manager=PositionRiskManager(break_even_trigger_percent=1.5),
        repository=repository,
        execution_gateway=gateway,
    )
    controller.add_position(position)

    result = controller.execute_exit_decision(
        position.position_id,
        _break_even_decision(position),
        PositionCalculator(entry_fee_rate=0.001, exit_fee_rate=0.001),
    )

    assert result is not None
    assert result.status is PositionStatus.OPEN
    assert result.realized_pnl == 0.0


def test_break_even_can_close_at_fee_aware_net_break_even():
    """A BE exit may close once the actual execution price covers both fees."""
    execution_price = 100.2003
    position = _position(execution_price)
    repository = PositionRepository()
    gateway = _PaperCloseGateway(executed_price=execution_price)
    controller = PositionController(
        risk_manager=PositionRiskManager(break_even_trigger_percent=1.5),
        repository=repository,
        execution_gateway=gateway,
    )
    controller.add_position(position)

    result = controller.execute_exit_decision(
        position.position_id,
        _break_even_decision(position),
        PositionCalculator(entry_fee_rate=0.001, exit_fee_rate=0.001),
    )

    assert result is not None
    assert result.status is PositionStatus.CLOSED
    assert result.realized_pnl >= 0.0
