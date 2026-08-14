from __future__ import annotations

from core.models import Position as CorePosition
from core.models import PositionStatus as CorePositionStatus
from core.paper_execution_adapter import PaperExecutionAdapter
from trade_manager import (
    CoreExecutionGateway,
    PositionCalculator,
    PositionController,
    PositionManagementFacade,
    PositionRepository,
    PositionRiskManager,
    PositionStatus,
)
from trade_manager import (
    PositionSide,
    core_to_trade_manager,
    trade_manager_to_core,
)
from trade_manager.integration_contracts import ExecutionOutcome, ExecutionSide, ExecutionRequest


def test_core_execution_gateway_paper_round_trip() -> None:
    adapter = PaperExecutionAdapter(initial_cash=1000.0, fee_rate=0.001)
    adapter.connect()
    adapter.set_market_price("BTCUSDT", 100.0)
    gateway = CoreExecutionGateway(adapter)

    opened = gateway.submit(
        ExecutionRequest(
            symbol="BTCUSDT",
            side=ExecutionSide.BUY,
            quantity=1.0,
            order_type="MARKET",
        )
    )
    assert opened.success is True
    assert opened.outcome is ExecutionOutcome.SUCCESS
    assert opened.executed_quantity == 1.0

    adapter.set_market_price("BTCUSDT", 102.0)
    closed = gateway.close_spot(symbol="BTCUSDT", quantity=1.0)
    assert closed.success is True
    assert closed.outcome is ExecutionOutcome.SUCCESS
    assert closed.executed_quantity == 1.0
    assert adapter.balance.assets.get("BTCUSDT", 0.0) == 0.0


def test_trade_manager_facade_commits_state_only_after_paper_execution() -> None:
    adapter = PaperExecutionAdapter(initial_cash=1000.0, fee_rate=0.001)
    adapter.connect()
    adapter.set_market_price("BTCUSDT", 100.0)

    gateway = CoreExecutionGateway(adapter)
    repository = PositionRepository()
    calculator = PositionCalculator()
    risk_manager = PositionRiskManager(calculator=calculator)
    controller = PositionController(risk_manager, repository, execution_gateway=gateway)
    facade = PositionManagementFacade(
        repository,
        controller,
        calculator,
        risk_manager,
        execution_gateway=gateway,
        risk_approval=lambda **_: True,
    )

    position = facade.open_position(
        symbol="BTCUSDT",
        quantity=1.0,
        entry_price=100.0,
        stop_loss=98.0,
    )

    assert position is not None
    assert position.status is PositionStatus.OPEN
    assert position.quantity == 1.0
    assert adapter.balance.assets["BTCUSDT"] == 1.0

    # A failed sell must not close or otherwise erase the owned position.
    adapter.balance.assets["BTCUSDT"] = 0.0
    failed_close = facade.close_position(position.position_id, exit_price=102.0)
    assert failed_close is None
    persisted = repository.get(position.position_id)
    assert persisted is not None
    assert persisted.status is PositionStatus.OPEN


def test_trade_manager_facade_closes_after_successful_paper_execution() -> None:
    adapter = PaperExecutionAdapter(initial_cash=1000.0, fee_rate=0.001)
    adapter.connect()
    adapter.set_market_price("ETHUSDT", 100.0)

    gateway = CoreExecutionGateway(adapter)
    repository = PositionRepository()
    calculator = PositionCalculator()
    risk_manager = PositionRiskManager(calculator=calculator)
    controller = PositionController(risk_manager, repository, execution_gateway=gateway)
    facade = PositionManagementFacade(
        repository,
        controller,
        calculator,
        risk_manager,
        execution_gateway=gateway,
        risk_approval=lambda **_: True,
    )

    position = facade.open_position(
        symbol="ETHUSDT",
        quantity=2.0,
        entry_price=100.0,
        stop_loss=98.0,
    )
    assert position is not None

    adapter.set_market_price("ETHUSDT", 110.0)
    closed = facade.close_position(position.position_id, exit_price=110.0)

    assert closed is not None
    assert closed.status is PositionStatus.CLOSED
    assert closed.quantity == 2.0
    assert closed.current_price == 110.0
    assert closed.exit_fee == 0.22
    assert closed.realized_pnl > 0.0
    assert adapter.balance.assets.get("ETHUSDT", 0.0) == 0.0


def test_core_position_conversion_preserves_spot_and_pnl_state() -> None:
    core = CorePosition(
        symbol="ETHUSDT",
        quantity=2.0,
        entry_price=100.0,
        trade_id="T-1",
        status=CorePositionStatus.RECOVERY,
        realized_profit=1.5,
        unrealized_profit=-3.0,
        fees_paid=0.25,
    )
    core.runtime.remaining_quantity = 2.0
    core.runtime.average_entry_price = 100.0
    core.runtime.last_price = 98.5

    tm = core_to_trade_manager(core)
    assert tm.side is PositionSide.LONG
    assert tm.status is PositionStatus.HOLD
    assert tm.realized_pnl == 1.5
    assert tm.gross_pnl == -1.5
    assert tm.total_fees == 0.25

    projected = trade_manager_to_core(tm, existing=core)
    assert projected.status is CorePositionStatus.RECOVERY
    assert projected.realized_profit == 1.5
    assert projected.unrealized_profit == -3.0
    assert projected.fees_paid == 0.25
