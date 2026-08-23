from core.brain_orchestrator import BrainPositionOrchestrator


class Position:
    def __init__(self):
        self.recovery_mode = False
        self.recovery_start_time = 0.0


def test_authoritative_exit_signal_cannot_be_overridden_by_recovery_or_brain():
    position = Position()
    decision = BrainPositionOrchestrator().evaluate_position(
        position,
        current_price=98.0,
        pnl_percent=-2.0,
        exit_signal="EXIT",
        indicators=None,
    )

    assert decision.action == "SELL"
    assert decision.authority == "EXIT_POLICY"
    assert decision.metadata["authoritative"] is True
