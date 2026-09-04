from __future__ import annotations

import pytest

from core.binance_protection import BinanceSpotProtection, ProtectionRequest


class FakeClient:
    def __init__(self):
        self.calls = []
        self.orders = []

    def create_oco_order(self, **kwargs):
        self.calls.append(("create_oco_order", kwargs))
        return {"orderListId": 123, "orders": []}

    def get_open_orders(self, *, symbol):
        self.calls.append(("get_open_orders", symbol))
        return list(self.orders)

    def cancel_order(self, *, symbol, orderId):
        self.calls.append(("cancel_order", symbol, orderId))
        return {"symbol": symbol, "orderId": orderId, "status": "CANCELED"}


def request() -> ProtectionRequest:
    return ProtectionRequest(
        symbol="ADAUSDT",
        quantity=10.0,
        take_profit_price=0.2242,
        stop_price=0.2161,
        stop_limit_price=0.2158,
    )


def test_sell_protection_uses_exchange_oco():
    client = FakeClient()
    result = BinanceSpotProtection(client).place_sell_protection(request())

    assert result["orderListId"] == 123
    name, params = client.calls[0]
    assert name == "create_oco_order"
    assert params["symbol"] == "ADAUSDT"
    assert params["side"] == "SELL"
    assert params["quantity"] == 10.0
    assert params["price"] == "0.2242"
    assert params["stopPrice"] == "0.2161"
    assert params["stopLimitPrice"] == "0.2158"
    assert params["stopLimitTimeInForce"] == "GTC"


def test_invalid_protection_prices_are_rejected_before_exchange_call():
    client = FakeClient()
    bad = ProtectionRequest("ADAUSDT", 10, 0.215, 0.2161, 0.2158)

    with pytest.raises(ValueError, match="above stop_price"):
        BinanceSpotProtection(client).place_sell_protection(bad)

    assert client.calls == []


def test_reconciliation_requires_active_sell_protection():
    orders = [
        {"side": "SELL", "status": "CANCELED", "type": "STOP_LOSS_LIMIT", "origQty": "10", "stopPrice": "0.2161"},
        {"side": "SELL", "status": "NEW", "type": "STOP_LOSS_LIMIT", "origQty": "10", "stopPrice": "0.2161"},
    ]
    assert BinanceSpotProtection.has_active_sell_protection(
        orders, quantity=10.0, stop_price=0.2161
    ) is True


def test_reconciliation_does_not_accept_wrong_quantity_or_stop():
    orders = [
        {"side": "SELL", "status": "NEW", "type": "STOP_LOSS_LIMIT", "origQty": "9", "stopPrice": "0.2161"},
        {"side": "SELL", "status": "NEW", "type": "STOP_LOSS_LIMIT", "origQty": "10", "stopPrice": "0.2170"},
    ]
    assert BinanceSpotProtection.has_active_sell_protection(
        orders, quantity=10.0, stop_price=0.2161
    ) is False


def test_reconciliation_does_not_accept_protection_for_larger_quantity():
    orders = [
        {"side": "SELL", "status": "NEW", "type": "STOP_LOSS_LIMIT", "origQty": "11", "stopPrice": "0.2161"},
    ]
    assert BinanceSpotProtection.has_active_sell_protection(
        orders, quantity=10.0, stop_price=0.2161
    ) is False
