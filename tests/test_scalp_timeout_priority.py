import time

from trade_manager.exit_policy import ExitPolicyPositionRiskManager
from trade_manager.models import Position, PositionSide, PositionStatus
from trade_manager.risk_manager import PositionExitReason


def make_position(*, age_minutes=121.0, price=99.0, stop_loss=95.0):
    return Position(
        position_id="POS-TEST-SCALP",
        symbol="TESTUSDT",
        side=PositionSide.LONG,
        status=PositionStatus.OPEN,
        quantity=1.0,
        entry_price=100.0,
        current_price=price,
        stop_loss=stop_loss,
        take_profit=None,
        opened_at=time.time() - age_minutes * 60.0,
        entry_metadata={"trade_mode": "SCALP"},
    )


def test_elapsed_scalp_holding_does_not_force_exit():
    manager = ExitPolicyPositionRiskManager(
        market_context_provider=lambda symbol: {"ema_100": "BULLISH", "market": {"overall": "BULLISH"}},
    )
    position = make_position()

    decision = manager.evaluate(position)

    assert decision.should_exit is False
    assert decision.reason is PositionExitReason.NONE
    assert "TIMEOUT" not in decision.message
    assert position.status is PositionStatus.HOLD


def test_hard_stop_still_wins_over_elapsed_holding_time():
    manager = ExitPolicyPositionRiskManager()
    position = make_position(price=94.0, stop_loss=95.0)

    decision = manager.evaluate(position)

    assert decision.should_exit is True
    assert decision.reason is PositionExitReason.STOP_LOSS


def test_swing_is_not_subject_to_elapsed_time_exit():
    manager = ExitPolicyPositionRiskManager()
    position = make_position()
    position.entry_metadata["trade_mode"] = "SWING"

    decision = manager.evaluate(position)

    assert decision.should_exit is False
    assert decision.reason is not PositionExitReason.RECOVERY_FAILED
