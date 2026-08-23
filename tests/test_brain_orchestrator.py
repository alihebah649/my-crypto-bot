from core.brain_orchestrator import BrainPositionOrchestrator


class Position:
    def __init__(self, entry_price=100.0):
        self.entry_price = entry_price
        self.recovery_mode = False
        self.recovery_start_time = 0.0


def test_hard_stop_cannot_be_overridden_by_recovery():
    position = Position()
    decision = BrainPositionOrchestrator().evaluate_position(
        position,
        current_price=96.0,
        pnl_percent=-4.0,
        hard_stop_triggered=True,
    )
    assert decision.action == "SELL"
    assert decision.authority == "HARD_EXIT"


def test_take_profit_is_hard_exit():
    decision = BrainPositionOrchestrator().evaluate_position(
        Position(),
        current_price=103.0,
        pnl_percent=3.0,
        take_profit_triggered=True,
    )
    assert decision.action == "SELL"
    assert decision.reason == "TAKE_PROFIT"


def test_losing_position_enters_recovery_and_can_hold():
    position = Position()
    decision = BrainPositionOrchestrator().evaluate_position(
        position,
        current_price=98.0,
        pnl_percent=-2.0,
        indicators=None,
    )
    assert position.recovery_mode is True
    assert decision.action == "HOLD"
    assert decision.metadata["recovery_active"] is True


def test_recovery_emergency_loss_reaches_execution_as_sell():
    position = Position()
    position.recovery_mode = True
    decision = BrainPositionOrchestrator().evaluate_position(
        position,
        current_price=91.0,
        pnl_percent=-9.0,
        indicators=None,
    )
    assert decision.action == "SELL"
    assert decision.authority == "RECOVERY_POLICY"


def test_recovery_score_is_normalized_for_brain():
    orchestrator = BrainPositionOrchestrator()
    assert orchestrator._recovery_score_percent(0) == 0.0
    assert orchestrator._recovery_score_percent(3) == 50.0
    assert orchestrator._recovery_score_percent(6) == 100.0
