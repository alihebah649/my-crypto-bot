"""Regression coverage for adaptive trailing take-profit behavior."""
from __future__ import annotations

from trade_manager.calculator import PositionCalculator
from trade_manager.models import Position, PositionSide, PositionStatus
from trade_manager.risk_manager import PositionExitReason, PositionRiskManager


def make_position(entry: float, current: float, stop: float, take_profit: float | None = None) -> Position:
    return Position(
        position_id="POS-TRAILING-TP-001",
        symbol="AVAXUSDT",
        side=PositionSide.LONG,
        status=PositionStatus.OPEN,
        quantity=50.0 / entry,
        entry_price=entry,
        current_price=current,
        stop_loss=stop,
        take_profit=take_profit,
    )


def manager() -> PositionRiskManager:
    return PositionRiskManager(
        atr_provider=lambda _symbol: 0.20,
        trailing_atr_multiplier=1.5,
        min_net_profit_percent=0.30,
        reward_to_risk_ratio=1.0,
        trailing_take_profit_enabled=True,
        trailing_take_profit_activation_r=2.0,
        trailing_take_profit_lock_r=1.0,
        calculator=PositionCalculator(0.001, 0.001),
    )


def test_take_profit_is_an_activation_trigger_not_a_hard_cap():
    position = make_position(100.0, 102.0, 99.0, take_profit=102.0)
    decision = manager().evaluate(position)

    assert decision.should_exit is False
    assert decision.reason is PositionExitReason.NONE
    assert position.metadata["take_profit_reached"] is True
    assert position.highest_price == 102.0


def test_adaptive_profit_lock_raises_floor_after_peak_reaches_two_risk_units():
    position = make_position(100.0, 104.0, 99.0)
    position.highest_price = 104.0
    risk_manager = manager()

    required = risk_manager._required_net_profit_percent(position)
    locked = risk_manager._trailing_take_profit_floor_percent(position, required)

    # Entry risk is 1%. At a peak above 2R, the default 1R lock trails the peak
    # instead of leaving the floor at the old fixed 1R minimum.
    assert required == 1.0
    assert locked > required
    assert locked > 2.5


def test_adaptive_profit_lock_allows_upside_then_exits_after_a_real_pullback():
    position = make_position(100.0, 104.0, 99.0)
    position.highest_price = 104.0
    risk_manager = manager()

    position.current_price = 103.0
    decision = risk_manager._check_trailing_stop(position)
    assert decision.should_exit is False

    position.current_price = 102.8
    decision = risk_manager._check_trailing_stop(position)
    assert decision.should_exit is True
    assert decision.reason is PositionExitReason.TRAILING_STOP
    assert "Adaptive Trailing Take Profit" in decision.message
    assert "Peak Net:" in decision.message
    assert "Locked Net:" in decision.message


def test_disabling_trailing_take_profit_preserves_hard_take_profit_behavior():
    position = make_position(100.0, 102.0, 99.0, take_profit=102.0)
    risk_manager = PositionRiskManager(
        trailing_take_profit_enabled=False,
        calculator=PositionCalculator(0.001, 0.001),
    )

    decision = risk_manager.evaluate(position)

    assert decision.should_exit is True
    assert decision.reason is PositionExitReason.TAKE_PROFIT
