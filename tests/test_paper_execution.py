"""Minimal BUY -> price rise -> SELL paper execution test.

This test never contacts Binance. It uses only the PaperExecutionAdapter.
"""

import pytest

from core.execution_models import OrderRequest, OrderSide, OrderType
from core.models import TradeType
from core.paper_execution_adapter import PaperExecutionAdapter


def make_request(symbol: str, side: OrderSide, quantity: float, client_order_id: str) -> OrderRequest:
    return OrderRequest(
        symbol=symbol,
        side=side,
        order_type=OrderType.MARKET,
        requested_quantity=quantity,
        client_order_id=client_order_id,
    )


def test_buy_price_rise_sell_with_fees():
    adapter = PaperExecutionAdapter(initial_cash=1000.0, fee_rate=0.001)

    # BUY at $100: cost = $500 + $0.50 fee.
    adapter.set_market_price("BTCUSDT", 100.0)
    buy = adapter.execute(
        make_request("BTCUSDT", OrderSide.BUY, 5.0, "paper-buy-001"),
        trade_type=TradeType.SCALPING,
    )

    assert buy.status.value == "FILLED"
    assert buy.executed_price == pytest.approx(100.0)
    assert buy.executed_quantity == pytest.approx(5.0)
    assert buy.fees.total == pytest.approx(0.50)
    assert adapter.balance.cash == pytest.approx(499.50)
    assert adapter.balance.assets["BTCUSDT"] == pytest.approx(5.0)

    # Price rises to $110, then SELL the same 5 BTC.
    adapter.set_market_price("BTCUSDT", 110.0)
    sell = adapter.execute(
        make_request("BTCUSDT", OrderSide.SELL, 5.0, "paper-sell-001"),
        trade_type=TradeType.SWING,
    )

    assert sell.status.value == "FILLED"
    assert sell.executed_price == pytest.approx(110.0)
    assert sell.executed_quantity == pytest.approx(5.0)
    assert sell.fees.total == pytest.approx(0.55)

    # Final cash = initial cash + sale proceeds - buy cost - both fees.
    # 1000 - 500 - 0.50 + 550 - 0.55 = 1049.95
    assert adapter.balance.cash == pytest.approx(1049.95)
    assert adapter.balance.assets["BTCUSDT"] == pytest.approx(0.0)


def test_paper_order_is_rejected_without_sufficient_cash():
    adapter = PaperExecutionAdapter(initial_cash=100.0, fee_rate=0.001)
    adapter.set_market_price("BTCUSDT", 100.0)

    result = adapter.execute(
        make_request("BTCUSDT", OrderSide.BUY, 2.0, "paper-buy-rejected"),
        trade_type=TradeType.SCALPING_SWING,
    )

    assert result.status.value == "REJECTED"
    assert result.reject_reason == "INSUFFICIENT_BALANCE"
    assert adapter.balance.cash == pytest.approx(100.0)
    assert adapter.balance.assets == {}
