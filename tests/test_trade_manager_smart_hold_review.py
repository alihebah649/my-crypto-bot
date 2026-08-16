"""Part-8 Smart Hold / REVIEW_REQUIRED contract tests."""

from __future__ import annotations

from core.paper_execution_adapter import PaperExecutionAdapter
from trade_manager.calculator import PositionCalculator
from trade_manager.controller import PositionController
from trade_manager.core_execution_gateway import CoreExecutionGateway
from trade_manager.facade import PositionManagementFacade
from trade_manager.models import PositionStatus
from trade_manager.repository import PositionRepository
from trade_manager.risk_manager import PositionRiskManager, PositionExitReason


def build_system():
    paper = PaperExecutionAdapter(initial_cash=1000.0, fee_rate=0.001)
    paper.connect()
    paper.set_market_price("BTCUSDT", 100.0)
    gateway = CoreExecutionGateway(paper)
    repository = PositionRepository()
    calculator = PositionCalculator()
    risk = PositionRiskManager(
        market_context_provider=lambda symbol: {"market": {"overall": "BULLISH"}, "volatility": "NORMAL"},
        atr_provider=lambda symbol: 2.0,
        ema_provider=lambda symbol: "BULLISH",
        max_holding_days=0.0,
    )
    controller = PositionController(risk, repository, gateway)
    facade = PositionManagementFacade(
        repository, controller, calculator, risk,
        execution_gateway=gateway,
        risk_approval=lambda **_: True,
    )
    return paper, facade, risk


def test_losing_position_enters_hold_before_review_deadline():
    paper, facade, risk = build_system()
    position = facade.open_position("BTCUSDT", 5.0, 100.0, 96.0)
    assert position is not None

    paper.set_market_price("BTCUSDT", 99.0)
    position.current_price = 99.0
    decision = risk.evaluate(position)

    assert decision.should_exit is False
    assert decision.reason is PositionExitReason.NONE
    assert position.status is PositionStatus.HOLD


def test_review_required_is_not_automatic_exit():
    paper, facade, risk = build_system()
    position = facade.open_position("BTCUSDT", 5.0, 100.0, 96.0)
    assert position is not None

    paper.set_market_price("BTCUSDT", 99.0)
    position.current_price = 99.0
    risk.evaluate(position)
    assert position.status is PositionStatus.HOLD

    # A second evaluation crosses the configured zero-day review boundary.
    decision = risk.evaluate(position)
    assert decision.review_required is True
    assert decision.should_exit is False
    assert position.status is PositionStatus.REVIEW_REQUIRED

    # Only an explicit close request may turn REVIEW_REQUIRED into CLOSED.
    closed = facade.close_position(position.position_id, 99.0)
    assert closed is not None
    assert closed.status is PositionStatus.CLOSED
    assert paper.balance.assets.get("BTCUSDT", 0.0) == 0.0
