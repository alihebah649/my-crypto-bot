from trade_manager.exit_watchdog import ExitWatchdog
from trade_manager.models import Position, PositionSide, PositionStatus
from trade_manager.risk_manager import PositionExitDecision, PositionExitReason


class FakeRepository:
    def __init__(self, positions):
        self.positions = positions

    def get_open_positions(self):
        return [p for p in self.positions if p.status is PositionStatus.OPEN]


class FakeRisk:
    def __init__(self, decisions):
        self.decisions = decisions
        self.calls = []

    def evaluate(self, position):
        self.calls.append(position.symbol)
        return self.decisions[position.symbol]


class FakeFacade:
    def __init__(self, positions):
        self.positions = positions
        self.calls = []

    def execute_decision(self, position_id, decision):
        self.calls.append((position_id, decision.reason))
        position = next(p for p in self.positions if p.position_id == position_id)
        if decision.should_exit:
            position.status = PositionStatus.CLOSED
        return position


def make_position(symbol):
    return Position(
        position_id=f"wd-{symbol}",
        symbol=symbol,
        side=PositionSide.LONG,
        status=PositionStatus.OPEN,
        quantity=1.0,
        entry_price=100.0,
        current_price=99.0,
        stop_loss=95.0,
        take_profit=None,
        entry_metadata={"trade_mode": "SCALP"},
    )


def test_watchdog_evaluates_all_active_positions_and_does_not_stop_after_one_exit():
    positions = [make_position(f"COIN{i}USDT") for i in range(1, 6)]
    decisions = {
        "COIN1USDT": PositionExitDecision(True, PositionExitReason.STOP_LOSS, 99.0),
        "COIN2USDT": PositionExitDecision(False, PositionExitReason.NONE, 99.0, "HOLD"),
        "COIN3USDT": PositionExitDecision(True, PositionExitReason.TRAILING_STOP, 99.0),
        "COIN4USDT": PositionExitDecision(False, PositionExitReason.NONE, 99.0, "RECOVERY"),
        "COIN5USDT": PositionExitDecision(True, PositionExitReason.RECOVERY_FAILED, 99.0),
    }
    repository = FakeRepository(positions)
    risk = FakeRisk(decisions)
    facade = FakeFacade(positions)

    result = ExitWatchdog(
        repository=repository,
        risk_manager=risk,
        facade=facade,
    ).run()

    assert result.evaluated == 5
    assert result.exit_signals == 3
    assert result.closed == 3
    assert result.failed == 0
    assert risk.calls == [p.symbol for p in positions]
    assert len(facade.calls) == 3
    assert positions[0].status is PositionStatus.CLOSED
    assert positions[1].status is PositionStatus.OPEN
    assert positions[2].status is PositionStatus.CLOSED
    assert positions[3].status is PositionStatus.OPEN
    assert positions[4].status is PositionStatus.CLOSED


def test_watchdog_continues_when_one_position_evaluation_fails():
    positions = [make_position("GOOD1USDT"), make_position("BROKENUSDT"), make_position("GOOD2USDT")]

    class RiskWithOneFailure:
        def evaluate(self, position):
            if position.symbol == "BROKENUSDT":
                raise RuntimeError("simulated evaluation failure")
            return PositionExitDecision(True, PositionExitReason.STOP_LOSS, position.current_price)

    facade = FakeFacade(positions)
    result = ExitWatchdog(
        repository=FakeRepository(positions),
        risk_manager=RiskWithOneFailure(),
        facade=facade,
    ).run()

    assert result.evaluated == 3
    assert result.exit_signals == 2
    assert result.closed == 2
    assert result.failed == 1
    assert positions[0].status is PositionStatus.CLOSED
    assert positions[1].status is PositionStatus.OPEN
    assert positions[2].status is PositionStatus.CLOSED
