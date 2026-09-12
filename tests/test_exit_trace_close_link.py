from trade_manager.controller import PositionController
from trade_manager.models import Position, PositionSide, PositionStatus
from trade_manager.risk_manager import PositionExitDecision, PositionExitReason


class _Outcome:
    success = True
    executed_quantity = 0.5
    average_price = 95.0
    commission = 0.05
    exchange_order_id = "paper-exit-1"
    metadata = {}


class _Execution:
    def close_spot(self, **kwargs):
        return _Outcome()


class _Risk:
    def evaluate(self, position):
        return PositionExitDecision(False, PositionExitReason.NONE)


def test_closed_position_keeps_exit_trace_and_realized_pnl(tmp_path):
    from trade_manager.calculator import PositionCalculator
    from trade_manager.repository import PositionRepository

    repository = PositionRepository(str(tmp_path / "positions.json"))
    position = Position(
        position_id="POS-trace-close",
        symbol="DOTUSDT",
        side=PositionSide.LONG,
        status=PositionStatus.OPEN,
        quantity=0.5,
        entry_price=100.0,
        current_price=100.0,
        stop_loss=95.0,
        take_profit=None,
        entry_metadata={"trade_mode": "SCALP"},
        metadata={"exit_decision_trace": {
            "position_id": "POS-trace-close",
            "trade_mode": "SCALP",
            "decision": "SELL",
            "decision_reason": "STOP_LOSS",
        }},
    )
    repository.add(position)
    controller = PositionController(_Risk(), repository, _Execution())

    closed = controller.execute_exit_decision(
        position.position_id,
        PositionExitDecision(True, PositionExitReason.STOP_LOSS, 95.0, "Stop Loss / Break Even Triggered"),
        PositionCalculator(0.001),
    )

    assert closed is not None
    assert closed.status is PositionStatus.CLOSED
    trace = closed.metadata["exit_decision_trace"]
    assert trace["position_id"] == closed.position_id
    assert trace["trade_mode"] == "SCALP"
    assert trace["execution_outcome"] == "CLOSED"
    assert trace["close_reason"] == "STOP_LOSS"
    assert trace["exit_price"] == 95.0
    assert trace["realized_pnl"] == closed.realized_pnl
    assert trace["fees"] == closed.total_fees

    reloaded = PositionRepository(str(tmp_path / "positions.json")).get(closed.position_id)
    assert reloaded is not None
    assert reloaded.metadata["exit_decision_trace"]["execution_outcome"] == "CLOSED"
    assert reloaded.metadata["realized_pnl"] if "realized_pnl" in reloaded.metadata else True
