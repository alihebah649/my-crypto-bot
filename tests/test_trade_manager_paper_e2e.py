"""End-to-end contract test for Trade Manager -> core paper execution.

This deliberately exercises the integration boundary rather than testing each
component in isolation. It proves that Part 6 risk approval gates the BUY,
Part 7/core execution owns fills, and the Trade Manager commits position state
only after successful execution.
"""

import pytest

from core.paper_execution_adapter import PaperExecutionAdapter
from trade_manager.calculator import PositionCalculator
from trade_manager.controller import PositionController
from trade_manager.core_execution_gateway import CoreExecutionGateway
from trade_manager.facade import PositionManagementFacade
from trade_manager.models import PositionStatus
from trade_manager.repository import PositionRepository
from trade_manager.risk_manager import PositionRiskManager


def build_facade(initial_cash: float = 1000.0):
    adapter = PaperExecutionAdapter(initial_cash=initial_cash, fee_rate=0.001)
    gateway = CoreExecutionGateway(adapter)
    repository = PositionRepository()
    calculator = PositionCalculator()
    risk_manager = PositionRiskManager(calculator=calculator)
    controller = PositionController(risk_manager, repository, gateway)
    facade = PositionManagementFacade(
        repository=repository,
        controller=controller,
        calculator=calculator,
        risk_manager=risk_manager,
        execution_gateway=gateway,
        risk_approval=lambda **_: True,
    )
    return adapter, facade


def test_trade_manager_paper_open_and_close_round_trip():
    adapter, facade = build_facade()
    adapter.set_market_price("BTCUSDT", 100.0)

    position = facade.open_position(
        symbol="BTCUSDT",
        quantity=5.0,
        entry_price=100.0,
        stop_loss=98.0,
    )

    assert position is not None
    assert position.status is PositionStatus.OPEN
    assert position.quantity == pytest.approx(5.0)
    assert position.entry_price == pytest.approx(100.0)
    assert position.entry_fee == pytest.approx(0.50)
    assert adapter.balance.assets["BTCUSDT"] == pytest.approx(5.0)

    adapter.set_market_price("BTCUSDT", 110.0)
    closed = facade.close_position(position.position_id, 110.0)

    assert closed is not None
    assert closed.status is PositionStatus.CLOSED
    assert closed.quantity == pytest.approx(5.0)
    assert closed.exit_fee == pytest.approx(0.55)
    assert closed.realized_pnl == pytest.approx(48.95)
    assert adapter.balance.assets["BTCUSDT"] == pytest.approx(0.0)
    assert adapter.balance.cash == pytest.approx(1048.95)


def test_trade_manager_does_not_create_position_when_risk_gate_rejects():
    adapter, facade = build_facade()
    adapter.set_market_price("ETHUSDT", 100.0)
    facade.risk_approval = lambda **_: False

    position = facade.open_position(
        symbol="ETHUSDT",
        quantity=5.0,
        entry_price=100.0,
        stop_loss=98.0,
    )

    assert position is None
    assert facade.get_open_positions() == []
    assert adapter.balance.assets == {}
    assert adapter.balance.cash == pytest.approx(1000.0)


def test_failed_close_never_marks_position_closed():
    adapter, facade = build_facade()
    adapter.set_market_price("SOLUSDT", 100.0)
    position = facade.open_position(
        symbol="SOLUSDT",
        quantity=5.0,
        entry_price=100.0,
        stop_loss=98.0,
    )
    assert position is not None

    # No paper balance remains for this asset after an external/independent
    # mutation. The core adapter must reject the SELL, so TM must keep it open.
    adapter.balance.assets["SOLUSDT"] = 0.0
    adapter.set_market_price("SOLUSDT", 90.0)

    closed = facade.close_position(position.position_id, 90.0)

    assert closed is None
    stored = facade.repository.get(position.position_id)
    assert stored is not None
    assert stored.status is PositionStatus.OPEN
    assert facade.get_open_positions()[0].status is PositionStatus.OPEN
