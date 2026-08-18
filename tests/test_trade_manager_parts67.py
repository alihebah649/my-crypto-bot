from __future__ import annotations

from trade_manager.part6_risk import (
    DailyRiskConfig,
    MarketContext,
    PortfolioSnapshot,
    PositionSizeCalculator,
    RiskConfig,
    RiskController,
    RiskDecision,
)
from trade_manager.part7_execution import (
    BrokerUtilities,
    ExecutionRequestBuilder,
    OrderSide,
    OrderType,
    TradeManagerExecutionPipeline,
)
from trade_manager.integration_contracts import (
    ExecutionOutcome,
    ExecutionOutcomeRecord,
    ExecutionSide,
)


class FakeGateway:
    def submit(self, request):
        return ExecutionOutcomeRecord(
            success=True,
            outcome=ExecutionOutcome.SUCCESS,
            symbol=request.symbol,
            side=request.side,
            requested_quantity=request.quantity,
            executed_quantity=request.quantity,
            average_price=request.price or 100.0,
            client_order_id=request.client_order_id,
        )

    def cancel(self, *, symbol, exchange_order_id=None, client_order_id=None):
        return ExecutionOutcomeRecord(
            success=True, outcome=ExecutionOutcome.CANCELLED, symbol=symbol,
            side=ExecutionSide.SELL, requested_quantity=0.0, executed_quantity=0.0,
            average_price=0.0, exchange_order_id=exchange_order_id,
            client_order_id=client_order_id,
        )

    def close_spot(self, *, symbol, quantity, client_order_id=None):
        return ExecutionOutcomeRecord(
            success=True, outcome=ExecutionOutcome.SUCCESS, symbol=symbol,
            side=ExecutionSide.SELL, requested_quantity=quantity, executed_quantity=quantity,
            average_price=101.0, client_order_id=client_order_id,
        )


def test_part6_spot_position_sizing_and_risk_gate():
    config = RiskConfig()
    sizing = PositionSizeCalculator(config).calculate(
        account_equity=1000.0, entry_price=100.0, stop_loss=98.0, leverage=1.0
    )
    # Normal Paper entry is capped by the configured $50 target notional.
    assert sizing.quantity == 0.5
    assert sizing.capital_used == 50.0
    assert sizing.risk_amount == 1.0

    controller = RiskController(config)
    account = PortfolioSnapshot(1000, 1000, 0, 1000, 0, 0, 0, 0, 0)
    market = MarketContext("BTCUSDT", 100, 99.9, 100.1, 0.2, 1.0, 1000000, 0.1, 0)
    result = controller.evaluate(account=account, symbol="BTCUSDT", signal=None, market=market)
    assert result.decision is RiskDecision.APPROVED


def test_part7_builder_pipeline_and_helpers():
    builder = ExecutionRequestBuilder("TM")
    order = builder.build_market_order(symbol="BTCUSDT", side=OrderSide.BUY, quantity=1.0)
    assert order.symbol == "BTCUSDT"
    assert order.order_type is OrderType.MARKET
    assert order.client_order_id.startswith("TM-")

    pipeline = TradeManagerExecutionPipeline(FakeGateway())
    response = pipeline.execute(order)
    assert response.ok is True
    assert response.result is not None
    assert response.result.executed_quantity == 1.0
    assert BrokerUtilities.normalize_symbol("btcusdt") == "BTCUSDT"


def test_part7_pipeline_close_is_spot_sell():
    pipeline = TradeManagerExecutionPipeline(FakeGateway())
    response = pipeline.close_spot(symbol="BTCUSDT", quantity=1.0)
    assert response.ok is True
    assert response.result is not None
    assert response.result.side == "SELL"
