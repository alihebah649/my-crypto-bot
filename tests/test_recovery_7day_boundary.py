"""Acceptance test: seven days is a Recovery boundary, not a timeout exit."""

from datetime import datetime, timedelta, timezone

from trade_manager.exit_policy import ExitPolicyPositionRiskManager
from trade_manager.models import Position, PositionSide, PositionStatus
from trade_manager.risk_manager import PositionExitReason


def make_position(opened_at: float) -> Position:
    return Position(
        position_id="test-recovery-7day",
        symbol="TESTUSDT",
        side=PositionSide.LONG,
        status=PositionStatus.OPEN,
        quantity=1.0,
        entry_price=100.0,
        current_price=99.0,
        stop_loss=95.0,
        take_profit=None,
        opened_at=opened_at,
        entry_metadata={"trade_mode": "SWING"},
    )


def test_seven_day_boundary_does_not_force_timeout_exit():
    opened_at = (datetime.now(timezone.utc) - timedelta(days=7)).timestamp()
    position = make_position(opened_at)

    manager = ExitPolicyPositionRiskManager(
        market_context_provider=lambda symbol: {
            "ema_100": "BULLISH",
            "market": {"overall": "BULLISH"},
            "volatility": "NORMAL",
        },
        atr_provider=lambda symbol: 0.5,
        ema_provider=lambda symbol: "BULLISH",
    )

    decision = manager.evaluate(position)

    assert decision.should_exit is False
    assert decision.reason is PositionExitReason.NONE
    assert "TIMEOUT" not in (decision.message or "")
