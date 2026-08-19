"""Regression coverage for reward/risk-aware profitable exits."""
from __future__ import annotations

from trade_manager.calculator import PositionCalculator
from trade_manager.models import Position, PositionSide, PositionStatus
from trade_manager.risk_manager import PositionExitReason, PositionRiskManager


def make_position(entry: float, current: float, stop: float) -> Position:
    return Position(
        position_id="POS-RR-FLOOR-001",
        symbol="AVAXUSDT",
        side=PositionSide.LONG,
        status=PositionStatus.OPEN,
        quantity=50.0 / entry,
        entry_price=entry,
        current_price=current,
        stop_loss=stop,
        take_profit=None,
    )


def test_trailing_profit_floor_tracks_initial_stop_risk():
    position = make_position(100.0, 101.0, 99.0)
    manager = PositionRiskManager(
        atr_provider=lambda _symbol: 0.20,
        trailing_atr_multiplier=1.5,
        min_net_profit_percent=0.30,
        reward_to_risk_ratio=1.0,
        calculator=PositionCalculator(0.001, 0.001),
    )

    floor = manager._minimum_profitable_exit_price(position)
    decision = manager._check_trailing_stop(position)

    assert floor > 101.0
    assert decision.should_exit is False
    assert decision.reason is PositionExitReason.NONE


def test_trailing_stop_can_exit_once_one_risk_unit_is_net_realized():
    position = make_position(100.0, 101.25, 99.0)
    position.highest_price = 102.0
    manager = PositionRiskManager(
        atr_provider=lambda _symbol: 0.20,
        trailing_atr_multiplier=1.5,
        min_net_profit_percent=0.30,
        reward_to_risk_ratio=1.0,
        calculator=PositionCalculator(0.001, 0.001),
    )

    decision = manager._check_trailing_stop(position)
    net = manager.calculator.calculate(position, position.current_price).net_pnl

    assert net > 0.0
    assert decision.should_exit is True
    assert decision.reason is PositionExitReason.TRAILING_STOP


def test_reward_risk_floor_never_drops_below_configured_absolute_floor():
    position = make_position(100.0, 100.4, 99.9)
    manager = PositionRiskManager(
        min_net_profit_percent=0.30,
        reward_to_risk_ratio=1.0,
        calculator=PositionCalculator(0.001, 0.001),
    )

    required = manager._required_net_profit_percent(position)

    assert required == 0.30


def test_reward_risk_floor_survives_break_even_activation():
    """Break-even must not erase the original 1R risk anchor."""
    position = make_position(100.0, 102.0, 98.0)
    manager = PositionRiskManager(
        atr_provider=lambda _symbol: 0.20,
        trailing_atr_multiplier=1.5,
        break_even_trigger_percent=1.5,
        min_net_profit_percent=0.30,
        reward_to_risk_ratio=1.0,
        calculator=PositionCalculator(0.001, 0.001),
    )

    manager.evaluate(position)

    assert position.metadata["initial_stop_loss"] == 98.0
    assert position.stop_loss > 98.0
    assert manager._required_net_profit_percent(position) == 2.0


def test_required_reward_risk_uses_persisted_entry_stop_after_restart_state():
    """A persisted position with a moved stop still retains its entry risk."""
    position = make_position(100.0, 102.0, 100.1001)
    position.metadata["initial_stop_loss"] = 98.0
    manager = PositionRiskManager(
        min_net_profit_percent=0.30,
        reward_to_risk_ratio=1.0,
        calculator=PositionCalculator(0.001, 0.001),
    )

    assert manager._required_net_profit_percent(position) == 2.0
