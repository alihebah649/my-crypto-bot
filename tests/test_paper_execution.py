"""Paper execution tests for the Shadow Trading Bot.

These tests never contact Binance. They validate only the paper execution
layer and keep strategy decisions separate from order execution.

Trading model:
- SCALPING is the default/primary trade mode.
- SWING is an exceptional recovery/hold mode for selected strong assets.
- The Trade Manager will own the decision to convert an eligible position;
  this file only verifies that the execution layer can execute the resulting
  orders correctly.
"""

import pytest

from core.execution_models import ExecutionContext, ExecutionRequest, OrderSide, OrderType
from core.models import TradeType
from core.paper_execution_adapter import PaperExecutionAdapter


def make_request(symbol: str, side: OrderSide, quantity: float, client_order_id: str, trade_type: TradeType) -> ExecutionRequest:
    return ExecutionRequest(
        symbol=symbol,
        side=side,
        order_type=OrderType.MARKET,
        quantity=quantity,
        client_order_id=client_order_id,
        context=ExecutionContext(metadata={"trade_type": trade_type.value}),
    )


def test_scalping_buy_price_rise_scalping_sell_with_fees():
    adapter = PaperExecutionAdapter(initial_cash=1000.0, fee_rate=0.001)

    adapter.set_market_price("BTCUSDT", 100.0)
    buy = adapter.execute(make_request("BTCUSDT", OrderSide.BUY, 5.0, "paper-scalp-buy-001", TradeType.SCALPING))

    assert buy.status.value == "FILLED"
    assert buy.executed_price == pytest.approx(100.0)
    assert buy.executed_quantity == pytest.approx(5.0)
    assert buy.fees.total == pytest.approx(0.50)
    assert buy.raw_response["trade_type"] == TradeType.SCALPING.value
    assert adapter.balance.cash == pytest.approx(499.50)
    assert adapter.balance.assets["BTCUSDT"] == pytest.approx(5.0)

    adapter.set_market_price("BTCUSDT", 110.0)
    sell = adapter.execute(make_request("BTCUSDT", OrderSide.SELL, 5.0, "paper-scalp-sell-001", TradeType.SCALPING))

    assert sell.status.value == "FILLED"
    assert sell.executed_price == pytest.approx(110.0)
    assert sell.executed_quantity == pytest.approx(5.0)
    assert sell.fees.total == pytest.approx(0.55)
    assert sell.raw_response["trade_type"] == TradeType.SCALPING.value

    # Final cash = 1000 - 500 - 0.50 + 550 - 0.55 = 1048.95.
    assert adapter.balance.cash == pytest.approx(1048.95)
    assert adapter.balance.assets["BTCUSDT"] == pytest.approx(0.0)


def test_recovery_position_can_exit_as_swing():
    adapter = PaperExecutionAdapter(initial_cash=1000.0, fee_rate=0.001)

    adapter.set_market_price("ETHUSDT", 100.0)
    buy = adapter.execute(make_request("ETHUSDT", OrderSide.BUY, 5.0, "paper-recovery-buy-001", TradeType.SCALPING))

    assert buy.status.value == "FILLED"
    assert adapter.balance.assets["ETHUSDT"] == pytest.approx(5.0)

    adapter.set_market_price("ETHUSDT", 96.0)
    assert adapter.get_market_price("ETHUSDT") < buy.executed_price

    # Trade Manager decides whether recovery/SWING is appropriate.
    adapter.set_market_price("ETHUSDT", 112.0)
    sell = adapter.execute(make_request("ETHUSDT", OrderSide.SELL, 5.0, "paper-recovery-sell-001", TradeType.SWING))

    assert sell.status.value == "FILLED"
    assert sell.executed_price == pytest.approx(112.0)
    assert sell.executed_quantity == pytest.approx(5.0)
    assert sell.raw_response["trade_type"] == TradeType.SWING.value
    assert sell.fees.total == pytest.approx(0.56)
    assert adapter.balance.assets["ETHUSDT"] == pytest.approx(0.0)

    # Final cash = 1000 - 500 - 0.50 + 560 - 0.56 = 1058.94.
    assert adapter.balance.cash == pytest.approx(1058.94)


def test_paper_order_is_rejected_without_sufficient_cash():
    adapter = PaperExecutionAdapter(initial_cash=100.0, fee_rate=0.001)
    adapter.set_market_price("BTCUSDT", 100.0)

    result = adapter.execute(make_request("BTCUSDT", OrderSide.BUY, 2.0, "paper-buy-rejected", TradeType.SCALPING))

    assert result.status.value == "REJECTED"
    assert result.reject_reason.value == "INSUFFICIENT_BALANCE"
    assert adapter.balance.cash == pytest.approx(100.0)
    assert adapter.balance.assets == {}
