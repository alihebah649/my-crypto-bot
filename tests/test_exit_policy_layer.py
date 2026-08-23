import time

from trade_manager.exit_policy import ExitPolicyPositionRiskManager
from trade_manager.models import Position, PositionSide, PositionStatus
from trade_manager.risk_manager import PositionExitReason


def make_position(*, mode="SCALP", entry=100.0, current=99.0, stop=98.0, opened_at=None):
    return Position(
        position_id=f"test-{mode.lower()}",
        symbol="TESTUSDT",
        side=PositionSide.LONG,
        status=PositionStatus.OPEN,
        quantity=1.0,
        entry_price=entry,
        current_price=current,
        stop_loss=stop,
        take_profit=None,
        opened_at=time.time() - (121 * 60 if opened_at is None else 0),
        entry_metadata={"trade_mode": mode},
    )


def manager():
    return ExitPolicyPositionRiskManager(
        market_context_provider=lambda symbol: {
            "ema_100": "BULLISH",
            "market": {"overall": "BULLISH"},
            "volatility": "NORMAL",
        },
        atr_provider=lambda symbol: 0.5,
        ema_provider=lambda symbol: "BULLISH",
        scalp_max_holding_minutes=120.0,
    )


def test_hard_stop_precedes_smart_hold():
    position = make_position(current=97.5, stop=98.0)
    decision = manager().evaluate(position)

    assert decision.should_exit is True
    assert decision.reason is PositionExitReason.STOP_LOSS


def test_scalp_timeout_prevents_indefinite_recovery_hold():
    position = make_position(current=99.0, stop=95.0)
    decision = manager().evaluate(position)

    assert decision.should_exit is True
    assert decision.reason is PositionExitReason.RECOVERY_FAILED
    assert "SCALP_TIMEOUT" in decision.message


def test_swing_keeps_existing_recovery_hold_behavior():
    position = make_position(mode="SWING", current=99.0, stop=95.0)
    decision = manager().evaluate(position)

    assert decision.should_exit is False
    assert position.status is PositionStatus.HOLD
