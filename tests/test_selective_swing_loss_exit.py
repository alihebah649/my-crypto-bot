"""Selective Swing policy: weak assets can exit a losing SCALPING position.

This is intentionally an execution-layer test. It verifies that a losing
SCALPING position can be closed without being relabeled as SWING merely
because the market moved against it.
"""

import pytest

from core.execution_models import ExecutionContext, ExecutionRequest, OrderSide, OrderType
from core.models import TradeType
from core.paper_execution_adapter import PaperExecutionAdapter


def request(symbol, side, quantity, client_order_id, trade_type):
    return ExecutionRequest(
        symbol=symbol,
        side=side,
        order_type=OrderType.MARKET,
        quantity=quantity,
        client_order_id=client_order_id,
        context=ExecutionContext(metadata={"trade_type": trade_type.value}),
    )


def test_weak_asset_can_exit_loss_without_swing_conversion():
    adapter = PaperExecutionAdapter(initial_cash=1000.0, fee_rate=0.001)

    adapter.set_market_price("ALTUSDT", 100.0)
    buy = adapter.execute(request("ALTUSDT", OrderSide.BUY, 5.0, "weak-loss-buy-001", TradeType.SCALPING))

    assert buy.status.value == "FILLED"
    assert buy.raw_response["trade_type"] == TradeType.SCALPING.value

    # The position is now losing. Loss alone must not convert it to SWING.
    adapter.set_market_price("ALTUSDT", 94.0)
    assert adapter.get_market_price("ALTUSDT") < buy.executed_price

    # Policy chooses to exit the weak asset rather than hold indefinitely.
    # The exit remains SCALPING because no Swing conversion was authorized.
    sell = adapter.execute(
        request("ALTUSDT", OrderSide.SELL, 5.0, "weak-loss-exit-001", TradeType.SCALPING)
    )

    assert sell.status.value == "FILLED"
    assert sell.raw_response["trade_type"] == TradeType.SCALPING.value
    assert sell.executed_price == pytest.approx(94.0)
    assert sell.fees.total == pytest.approx(0.47)
    assert adapter.balance.assets["ALTUSDT"] == pytest.approx(0.0)

    # 1000 - 500 - 0.50 + 470 - 0.47 = 969.03
    assert adapter.balance.cash == pytest.approx(969.03)
