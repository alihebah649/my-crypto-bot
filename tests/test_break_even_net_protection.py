"""Regression tests for fee-aware Break-Even net-profit protection."""

from trade_manager.models import Position, PositionSide, PositionStatus
from trade_manager.risk_manager import PositionExitReason, PositionRiskManager


def _position(current_price: float, *, break_even_activated: bool = False) -> Position:
    position = Position(
        position_id="BE-REGRESSION",
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        status=PositionStatus.OPEN,
        quantity=1.0,
        entry_price=100.0,
        current_price=current_price,
        stop_loss=98.0,
        take_profit=None,
    )
    if break_even_activated:
        position.metadata["break_even_activated"] = True
        position.stop_loss = 100.2002002002
    return position


def test_break_even_must_not_exit_below_fee_aware_net_break_even():
    """Once BE is active, a price below the fee-aware BE must not close the trade.

    With 0.1% entry and 0.1% exit fees, a 100.0 entry requires about 100.2002
    to reach true net break-even. A price such as 100.10 is still a net loss.
    """
    manager = PositionRiskManager(
        break_even_trigger_percent=1.5,
        min_net_profit_percent=0.30,
        reward_to_risk_ratio=1.0,
    )
    position = _position(100.10, break_even_activated=True)

    decision = manager.evaluate(position)

    assert decision.should_exit is False
    assert decision.reason is PositionExitReason.NONE


def test_break_even_can_exit_at_or_above_fee_aware_net_break_even():
    """The BE protection may close once the executed price covers both fees."""
    manager = PositionRiskManager(
        break_even_trigger_percent=1.5,
        min_net_profit_percent=0.30,
        reward_to_risk_ratio=1.0,
    )
    position = _position(100.2003, break_even_activated=True)

    decision = manager.evaluate(position)

    assert decision.should_exit is True
    assert decision.reason is PositionExitReason.BREAK_EVEN
    assert decision.exit_price == 100.2003
