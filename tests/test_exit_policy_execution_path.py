import time

from trade_manager.controller import PositionController
from trade_manager.exit_policy import ExitPolicyPositionRiskManager
from trade_manager.integration_contracts import ExecutionOutcome, ExecutionOutcomeRecord, ExecutionSide
from trade_manager.models import Position, PositionSide, PositionStatus
from trade_manager.repository import PositionRepository


class FakeExitGateway:
    def __init__(self, price=99.0):
        self.price = price
        self.calls = []

    def close_spot(self, *, symbol, quantity, client_order_id=None):
        self.calls.append((symbol, quantity, client_order_id))
        return ExecutionOutcomeRecord(
            success=True,
            outcome=ExecutionOutcome.SUCCESS,
            symbol=symbol,
            side=ExecutionSide.SELL,
            requested_quantity=quantity,
            executed_quantity=quantity,
            average_price=self.price,
            commission=self.price * quantity * 0.001,
        )

    def submit(self, request):
        raise AssertionError("submit() is not part of the exit-path test")

    def cancel(self, **kwargs):
        raise AssertionError("cancel() is not part of the exit-path test")


def test_scalp_timeout_decision_reaches_execution_and_closes_position():
    repository = PositionRepository()
    gateway = FakeExitGateway(price=99.0)
    risk = ExitPolicyPositionRiskManager(
        market_context_provider=lambda symbol: {
            "ema_100": "BULLISH",
            "market": {"overall": "BULLISH"},
            "volatility": "NORMAL",
        },
        atr_provider=lambda symbol: 0.5,
        ema_provider=lambda symbol: "BULLISH",
        scalp_max_holding_minutes=120.0,
    )
    controller = PositionController(risk, repository, gateway)

    position = Position(
        position_id="scalp-timeout-e2e",
        symbol="TESTUSDT",
        side=PositionSide.LONG,
        status=PositionStatus.OPEN,
        quantity=5.0,
        entry_price=100.0,
        current_price=99.0,
        stop_loss=95.0,
        take_profit=None,
        opened_at=time.time() - 121 * 60,
        entry_metadata={"trade_mode": "SCALP"},
    )
    repository.add(position)

    decision = risk.evaluate(position)
    assert decision.should_exit is True
    assert "SCALP_TIMEOUT" in decision.message

    closed = controller.execute_exit_decision(position.position_id, decision, risk.calculator)

    assert closed is not None
    assert closed.status is PositionStatus.CLOSED
    assert closed.close_reason.name == "RECOVERY_FAILED"
    assert gateway.calls == [("TESTUSDT", 5.0, None)]
    assert closed.realized_pnl < 0
    assert closed.exit_metadata["exit_reason"] == "RECOVERY_FAILED"
