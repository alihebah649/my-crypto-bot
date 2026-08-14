"""Integration contract tests for Trade Manager Parts 1-8.

These tests never contact an exchange. They verify that the lifecycle/risk
models, Part-7 execution boundary, Part-8 controller, and core-position bridge
can coexist without importing incompatible position definitions.
"""

import pytest

from core.models import Position as CorePosition
from trade_manager import (
    PositionCalculator,
    PositionCloseReason,
    PositionManagementFacade,
    PositionRepository,
    PositionRiskManager,
    PositionStatus,
    RiskManager,
    from_core_position,
)


def make_facade() -> PositionManagementFacade:
    repository = PositionRepository()
    calculator = PositionCalculator(entry_fee_rate=0.001, exit_fee_rate=0.001)
    exit_risk = PositionRiskManager(calculator=calculator)
    return PositionManagementFacade(
        repository=repository,
        controller=__import__("trade_manager.controller", fromlist=["PositionController"]).PositionController(
            exit_risk, repository
        ),
        calculator=calculator,
        risk_manager=exit_risk,
        entry_risk_manager=RiskManager(),
    )


def test_part6_entry_gate_and_part8_open_share_one_contract():
    facade = make_facade()
    risk = facade.validate_entry(
        equity=1000.0,
        free_balance=1000.0,
        entry_price=100.0,
        stop_loss=98.0,
    )
    assert risk.approved
    assert risk.metadata["quantity"] > 0

    position = facade.open_position(
        "BTCUSDT", risk.metadata["quantity"], 100.0, 98.0,
        risk_evaluation=risk,
    )
    assert position.status is PositionStatus.OPEN
    assert facade.get_open_positions()[0].position_id == position.position_id


def test_manual_close_uses_manual_reason_and_net_fees():
    facade = make_facade()
    position = facade.open_position("BTCUSDT", 2.0, 100.0, 98.0)
    closed = facade.close_position(position.position_id, 110.0, PositionCloseReason.MANUAL)

    assert closed is not None
    assert closed.status is PositionStatus.CLOSED
    assert closed.close_reason is PositionCloseReason.MANUAL
    assert closed.total_fees == pytest.approx(0.42)
    assert closed.realized_pnl == pytest.approx(19.58)


def test_core_position_bridge_preserves_spot_position_state():
    core_position = CorePosition(
        symbol="ETHUSDT",
        quantity=2.0,
        entry_price=100.0,
        highest_price=105.0,
        stop_loss=97.0,
        take_profit=110.0,
        trade_id="CORE-1",
    )
    core_position.runtime.remaining_quantity = 2.0
    core_position.runtime.last_price = 104.0
    core_position.strategy_name = "Shadow Trading System V3"

    tm_position = from_core_position(core_position)

    assert tm_position.position_id == "CORE-1"
    assert tm_position.symbol == "ETHUSDT"
    assert tm_position.quantity == pytest.approx(2.0)
    assert tm_position.current_price == pytest.approx(104.0)
    assert tm_position.stop_loss == pytest.approx(97.0)
    assert tm_position.metadata["strategy_name"] == "Shadow Trading System V3"
