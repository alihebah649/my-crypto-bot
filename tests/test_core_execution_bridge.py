"""Contract tests for the core ExecutionAdapter -> Trade Manager Part-7 boundary."""

from core.paper_execution_adapter import PaperExecutionAdapter
from trade_manager.core_execution_adapter import CoreExecutionBrokerAdapter
from trade_manager.execution import ExecutionOrder, ExecutionPipeline, OrderSide


def test_paper_adapter_is_reachable_through_part7_contract():
    paper = PaperExecutionAdapter(initial_cash=1000.0, fee_rate=0.001)
    paper.connect()
    paper.set_market_price("BTCUSDT", 100.0)

    broker = CoreExecutionBrokerAdapter(paper, strategy_name="contract-test")
    pipeline = ExecutionPipeline(broker)

    result = pipeline.execute(
        ExecutionOrder(symbol="BTCUSDT", side=OrderSide.BUY, quantity=2.0)
    )

    assert result.success
    assert result.executed_quantity == 2.0
    assert result.average_price == 100.0
    assert result.exchange_order_id


def test_part7_bridge_preserves_rejection_without_touching_trade_manager_state():
    paper = PaperExecutionAdapter(initial_cash=10.0, fee_rate=0.001)
    paper.connect()
    paper.set_market_price("BTCUSDT", 100.0)

    broker = CoreExecutionBrokerAdapter(paper)
    pipeline = ExecutionPipeline(broker)

    result = pipeline.execute(
        ExecutionOrder(symbol="BTCUSDT", side=OrderSide.BUY, quantity=2.0)
    )

    assert not result.success
    assert result.executed_quantity == 0.0
    assert "INSUFFICIENT_BALANCE" in result.message
