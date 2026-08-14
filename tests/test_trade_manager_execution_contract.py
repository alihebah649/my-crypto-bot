"""Focused tests for the Part-7 -> core execution integration boundary."""

from types import SimpleNamespace

from core.execution_models import OrderStatus
from trade_manager.execution import ExecutionOrder, OrderSide, ExecutionStatus
from trade_manager.core_execution_adapter import CoreExecutionBrokerAdapter


class FakeCoreAdapter:
    exchange_name = "FAKE"

    def __init__(self, result=None, order=None):
        self.result = result
        self.order = order or {}

    def execute(self, request):
        return self.result

    def get_order(self, symbol, order_id):
        return self.order

    def cancel_order(self, symbol, order_id):
        return True


def test_partial_fill_is_not_a_successful_full_close():
    result = SimpleNamespace(
        status=OrderStatus.PARTIALLY_FILLED,
        executed_quantity=2.0,
        executed_price=100.0,
        average_price=100.0,
        fees=SimpleNamespace(total=0.2),
        exchange_order_id="EX-1",
        client_order_id="TM-1",
        message="PARTIALLY_FILLED",
        raw_response={},
    )
    adapter = CoreExecutionBrokerAdapter(FakeCoreAdapter(result))

    out = adapter.submit_order(
        ExecutionOrder("BTCUSDT", OrderSide.SELL, 5.0, client_order_id="TM-1")
    )

    assert out.status is ExecutionStatus.PARTIALLY_FILLED
    assert out.executed_quantity == 2.0
    assert out.remaining_quantity == 3.0
    assert out.success is False
    assert out.fully_filled is False


def test_query_uses_original_quantity_and_cumulative_quote_for_average_price():
    raw = {
        "orderId": 42,
        "clientOrderId": "TM-2",
        "symbol": "ETHUSDT",
        "side": "SELL",
        "status": "FILLED",
        "origQty": "5",
        "executedQty": "5",
        "price": "0",
        "cummulativeQuoteQty": "550",
    }
    adapter = CoreExecutionBrokerAdapter(FakeCoreAdapter(order=raw))

    out = adapter.query_order("ETHUSDT", order_id="42")

    assert out.status is ExecutionStatus.FILLED
    assert out.requested_quantity == 5.0
    assert out.executed_quantity == 5.0
    assert out.remaining_quantity == 0.0
    assert out.average_price == 110.0
    assert out.success is True
