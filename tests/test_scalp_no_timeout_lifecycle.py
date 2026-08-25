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


def test_scalp_does_not_exit_automatically_after_120_minutes():
    manager = ExitPolicyPositionRiskManager(
        market_context_provider=lambda symbol: {"ema_100": "BULLISH", "market": {"overall": "BULLISH"}},
    )
    position = make_position(age_minutes=121.0, price=99.0, stop_loss=95.0)

    decision = manager.evaluate(position)

    assert decision.should_exit is False
    assert decision.reason is PositionExitReason.NONE
    assert decision.review_required is False


def test_hard_stop_still_wins_for_old_scalp_position():
    manager = ExitPolicyPositionRiskManager()
    position = make_position(age_minutes=121.0, price=94.0, stop_loss=95.0)

    decision = manager.evaluate(position)

    assert decision.should_exit is True
    assert decision.reason is PositionExitReason.STOP_LOSS


def test_scalp_can_remain_in_smart_hold_after_long_age():
    manager = ExitPolicyPositionRiskManager(
        market_context_provider=lambda symbol: {
            "ema_100": "BULLISH",
            "market": {"overall": "BULLISH"},
            "volatility": "NORMAL",
        },
    )
    position = make_position(age_minutes=240.0, price=97.0, stop_loss=95.0)

    decision = manager.evaluate(position)

    assert decision.should_exit is False
    assert decision.reason is PositionExitReason.NONE
    assert decision.hold_reason
    assert position.status is PositionStatus.HOLD


def test_swing_is_unaffected_by_scalp_timeout_removal():
    manager = ExitPolicyPositionRiskManager()
    position = make_position(age_minutes=240.0, price=99.0, stop_loss=95.0)
    position.entry_metadata["trade_mode"] = "SWING"

    decision = manager.evaluate(position)

    assert decision.should_exit is False
    assert decision.reason is PositionExitReason.NONE
