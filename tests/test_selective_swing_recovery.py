"""Selective SCALPING -> SWING recovery behavior.

These tests intentionally model the policy boundary, not the Trade Manager
implementation itself:
- SCALPING is the normal/default trade type.
- A losing position does not automatically become SWING.
- Only an explicitly eligible strong asset may be exited as SWING after recovery.
- A weak asset remains SCALPING and may be exited instead of being held forever.
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


def test_strong_asset_can_recover_from_scalping_to_swing():
    adapter = PaperExecutionAdapter(initial_cash=1000.0, fee_rate=0.001)

    adapter.set_market_price("ETHUSDT", 100.0)
    buy = adapter.execute(request("ETHUSDT", OrderSide.BUY, 5.0, "strong-buy-001", TradeType.SCALPING))
    assert buy.status.value == "FILLED"

    # Temporary loss: this alone must not change the trade type.
    adapter.set_market_price("ETHUSDT", 96.0)
    assert adapter.get_market_price("ETHUSDT") < buy.executed_price
    assert buy.raw_response["trade_type"] == TradeType.SCALPING.value

    # The policy layer has independently decided that ETH is eligible for
    # recovery/SWING. The execution layer simply executes that resulting order.
    adapter.set_market_price("ETHUSDT", 112.0)
    sell = adapter.execute(request("ETHUSDT", OrderSide.SELL, 5.0, "strong-swing-exit-001", TradeType.SWING))

    assert sell.status.value == "FILLED"
    assert sell.raw_response["trade_type"] == TradeType.SWING.value
    assert sell.executed_price == pytest.approx(112.0)
    assert sell.fees.total == pytest.approx(0.56)
    assert adapter.balance.cash == pytest.approx(1058.94)


def test_weak_asset_does_not_automatically_convert_to_swing():
    adapter = PaperExecutionAdapter(initial_cash=1000.0, fee_rate=0.001)

    adapter.set_market_price("ALTUSDT", 100.0)
    buy = adapter.execute(request("ALTUSDT", OrderSide.BUY, 5.0, "weak-buy-001", TradeType.SCALPING))
    assert buy.status.value == "FILLED"

    # A loss does not authorize an automatic SCALPING -> SWING conversion.
    adapter.set_market_price("ALTUSDT", 94.0)
    assert adapter.get_market_price("ALTUSDT") < buy.executed_price
    assert buy.raw_response["trade_type"] == TradeType.SCALPING.value

    # For a weak asset, the policy can choose to close the position rather
    # than hold it indefinitely. The execution request remains SCALPING.
    sell = adapter.execute(request("ALTUSDT", OrderSide.SELL, 5.0, "weak-scalp-exit-001", TradeType.SCALPING))

    assert sell.status.value == "FILLED"
    assert sell.raw_response["trade_type"] == TradeType.SCALPING.value
    assert sell.executed_price == pytest.approx(94.0)
    assert sell.fees.total == pytest.approx(0.47)
    assert adapter.balance.assets["ALTUSDT"] == pytest.approx(0.0)
