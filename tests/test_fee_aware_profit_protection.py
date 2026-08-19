"""Regression coverage for fee-aware profitable exits."""
from __future__ import annotations

from trade_manager.calculator import PositionCalculator
from trade_manager.models import Position, PositionSide, PositionStatus
from trade_manager.risk_manager import PositionExitReason, PositionRiskManager


def make_position(entry: float, current: float, atr_percent: float = 0.20) -> Position:
    return Position(
        position_id="POS-FEE-AWARE-001",
        symbol="AVAXUSDT",
        side=PositionSide.LONG,
        status=PositionStatus.OPEN,
        quantity=50.0 / entry,
        entry_price=entry,
        current_price=current,
        stop_loss=entry * 0.99,
    )


def test_trailing_stop_never_locks_a_net_loss_after_fees():
    position = make_position(6.343, 6.350)
    position.highest_price = 6.390
    manager = PositionRiskManager(
        atr_provider=lambda _symbol: 0.20,
        trailing_atr_multiplier=1.5,
        calculator=PositionCalculator(0.001, 0.001),
    )

    decision = manager._check_trailing_stop(position)

    assert decision.should_exit is False
    assert decision.reason is PositionExitReason.NONE


def test_trailing_stop_can_exit_only_after_fee_aware_profit_floor():
    position = make_position(100.0, 101.0)
    position.highest_price = 102.0
    manager = PositionRiskManager(
        atr_provider=lambda _symbol: 0.20,
        trailing_atr_multiplier=1.5,
        min_net_profit_percent=0.30,
        calculator=PositionCalculator(0.001, 0.001),
    )

    decision = manager._check_trailing_stop(position)

    assert decision.should_exit is True
    assert decision.reason is PositionExitReason.TRAILING_STOP
    assert decision.exit_price == 101.0


def test_fee_aware_profit_floor_is_above_fee_break_even():
    position = make_position(100.0, 100.7)
    manager = PositionRiskManager(calculator=PositionCalculator(0.001, 0.001))

    break_even = manager.calculator.break_even_price(position)
    floor = manager._minimum_profitable_exit_price(position)

    assert break_even > 100.0
    assert floor > break_even
    assert position.current_price < floor
