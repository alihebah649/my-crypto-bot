from trade_manager.exit_watchdog import ExitWatchdog
from trade_manager.models import Position, PositionSide, PositionStatus
from trade_manager.risk_manager import PositionExitDecision, PositionExitReason


class FakeRepository:
    def __init__(self, position):
        self.position = position

    def get_open_positions(self):
        return [self.position]


class FakeRisk:
    def evaluate(self, position):
        return PositionExitDecision(
            True,
            PositionExitReason.RECOVERY_FAILED,
            position.current_price,
            "SCALP_TIMEOUT after 121m; P&L -1.00%",
        )


class FakeFacade:
    def __init__(self, position):
        self.position = position

    def execute_decision(self, position_id, decision):
        self.position.status = PositionStatus.CLOSED
        return self.position


def test_watchdog_evaluates_active_position_without_entry_signal():
    position = Position(
        position_id="watchdog-1",
        symbol="TESTUSDT",
        side=PositionSide.LONG,
        status=PositionStatus.OPEN,
        quantity=1.0,
        entry_price=100.0,
        current_price=99.0,
        stop_loss=95.0,
        take_profit=None,
        entry_metadata={"trade_mode": "SCALP"},
    )
    facade = FakeFacade(position)
    result = ExitWatchdog(
        repository=FakeRepository(position),
        risk_manager=FakeRisk(),
        facade=facade,
    ).run()

    assert result.evaluated == 1
    assert result.exit_signals == 1
    assert result.closed == 1
    assert result.failed == 0
    assert position.status is PositionStatus.CLOSED
