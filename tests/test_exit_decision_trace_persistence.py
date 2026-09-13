from trade_manager.exit_policy import ExitPolicyPositionRiskManager
from trade_manager.models import Position, PositionSide, PositionStatus
from trade_manager.repository import PositionRepository


def test_exit_decision_trace_survives_restart_persistence(tmp_path):
    path = str(tmp_path / "positions.json")
    repository = PositionRepository(path)
    position = Position(
        position_id="POS-persist-trace",
        symbol="ATOMUSDT",
        side=PositionSide.LONG,
        status=PositionStatus.OPEN,
        quantity=0.5,
        entry_price=100.0,
        current_price=99.0,
        stop_loss=95.0,
        take_profit=None,
        entry_metadata={"trade_mode": "SCALP"},
    )
    repository.add(position)

    ExitPolicyPositionRiskManager().evaluate(position)
    repository.update(position)

    restored = PositionRepository(path).get(position.position_id)
    assert restored is not None
    trace = restored.metadata["exit_decision_trace"]
    assert trace["position_id"] == position.position_id
    assert trace["symbol"] == "ATOMUSDT"
    assert trace["trade_mode"] == "SCALP"
    assert trace["current_price"] == 99.0
    assert "evaluation_timestamp" in trace
