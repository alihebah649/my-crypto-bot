"""Application-level Part-6 -> Trade Manager -> Paper execution test."""

import pytest

from core.paper_execution_adapter import PaperExecutionAdapter
from trade_manager.core_execution_gateway import CoreExecutionGateway
from trade_manager.core_risk_gateway import CoreRiskGateway
from trade_manager.core_risk_providers import CallableMarketContextProvider
from trade_manager.facade import PositionManagementFacade
from trade_manager.calculator import PositionCalculator
from trade_manager.controller import PositionController
from trade_manager.integration_contracts import RiskSizingRequest
from trade_manager.models import PositionStatus
from trade_manager.part6_risk import (
    MarketContext,
    PositionSizeCalculator,
    PortfolioSnapshot,
    RiskConfig,
    RiskController,
)
from trade_manager.repository import PositionRepository
from trade_manager.risk_manager import PositionRiskManager


class StaticPortfolioProvider:
    def snapshot(self):
        return PortfolioSnapshot(
            account_balance=1000.0,
            account_equity=1000.0,
            used_margin=0.0,
            free_margin=1000.0,
            floating_pnl=0.0,
            daily_pnl=0.0,
            weekly_pnl=0.0,
            monthly_pnl=0.0,
            open_positions=0,
        )


def market_provider():
    return CallableMarketContextProvider(
        lambda symbol: MarketContext(
            symbol=symbol,
            last_price=100.0,
            bid=99.99,
            ask=100.01,
            spread_percent=0.02,
            atr=2.0,
            volume=1_000_000.0,
            volatility=0.02,
            timestamp=1.0,
        )
    )


def build_system():
    paper = PaperExecutionAdapter(initial_cash=1000.0, fee_rate=0.001)
    paper.connect()
    paper.set_market_price("BTCUSDT", 100.0)

    execution = CoreExecutionGateway(paper)
    repository = PositionRepository()
    calculator = PositionCalculator()
    position_risk = PositionRiskManager(calculator=calculator)
    controller = PositionController(position_risk, repository, execution)

    risk_config = RiskConfig()
    risk_controller = RiskController(config=risk_config)
    sizing = PositionSizeCalculator(risk_config)
    account = StaticPortfolioProvider()
    market = market_provider()
    risk_gateway = CoreRiskGateway(
        controller=risk_controller,
        position_sizer=sizing,
        portfolio_provider=account,
        market_provider=market,
    )

    facade = PositionManagementFacade(
        repository=repository,
        controller=controller,
        calculator=calculator,
        risk_manager=position_risk,
        execution_gateway=execution,
        risk_approval=lambda **kwargs: risk_gateway.approve(
            RiskSizingRequest(
                symbol=kwargs["symbol"],
                entry_price=kwargs["entry_price"],
                stop_loss=kwargs["stop_loss"],
                account_equity=1000.0,
                free_balance=1000.0,
                leverage=1.0,
            )
        ).approved,
    )
    return paper, risk_gateway, facade


def test_part6_approval_reaches_trade_manager_and_paper_execution():
    paper, risk_gateway, facade = build_system()

    approval = risk_gateway.approve(
        RiskSizingRequest(
            symbol="BTCUSDT",
            entry_price=100.0,
            stop_loss=98.0,
            account_equity=1000.0,
            free_balance=1000.0,
            leverage=1.0,
        )
    )

    assert approval.approved is True
    assert approval.quantity == pytest.approx(0.5)
    assert approval.position_value == pytest.approx(50.0)
    assert approval.metadata["target_position_value"] == pytest.approx(50.0)

    position = facade.open_position(
        symbol="BTCUSDT",
        quantity=approval.quantity,
        entry_price=100.0,
        stop_loss=98.0,
    )

    assert position is not None
    assert position.status is PositionStatus.OPEN
    assert position.entry_price == pytest.approx(100.0)
    assert paper.balance.assets["BTCUSDT"] == pytest.approx(0.5)
    # $50 notional + $0.05 entry fee was consumed from the $1000 account.
    assert paper.balance.cash == pytest.approx(949.95)


def test_part6_rejects_spot_leverage_above_one():
    _, risk_gateway, _ = build_system()

    approval = risk_gateway.approve(
        RiskSizingRequest(
            symbol="BTCUSDT",
            entry_price=100.0,
            stop_loss=98.0,
            account_equity=1000.0,
            free_balance=1000.0,
            leverage=2.0,
        )
    )

    assert approval.approved is False
    assert approval.reason == "LEVERAGE_NOT_ALLOWED_SPOT"
