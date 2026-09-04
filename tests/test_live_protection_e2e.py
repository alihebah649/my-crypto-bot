"""End-to-end safety-path tests for a filled Spot BUY.

These tests exercise the orchestration boundary from a filled BUY through
exchange-side protection confirmation.  They deliberately use a fake
exchange client: no real Binance client, strategy, Trade Manager, or Paper
Execution path is changed by this test module.
"""
from __future__ import annotations

from core.binance_protection import BinanceSpotProtection, ProtectionRequest
from core.live_protection_flow import LiveProtectionFlow
from core.live_protection_gate import ProtectionState


class FakeProtectionClient:
    def __init__(self, orders):
        self.orders = list(orders)
        self.created = []
        self.fail_create = False
        self.fail_read = False

    def create_oco_order(self, **kwargs):
        if self.fail_create:
            raise RuntimeError("exchange unavailable")
        self.created.append(kwargs)
        return {"orderListId": 123, **kwargs}

    def get_open_orders(self, *, symbol: str):
        if self.fail_read:
            raise RuntimeError("read unavailable")
        return [order for order in self.orders if order.get("symbol", symbol) == symbol]

    def cancel_order(self, *, symbol: str, orderId):
        return {"symbol": symbol, "orderId": orderId, "status": "CANCELED"}


def request() -> ProtectionRequest:
    return ProtectionRequest(
        symbol="ADAUSDT",
        quantity=10.0,
        take_profit_price=0.2240,
        stop_price=0.2161,
        stop_limit_price=0.2159,
    )


def confirmed_order():
    return {
        "symbol": "ADAUSDT",
        "side": "SELL",
        "status": "NEW",
        "type": "STOP_LOSS_LIMIT",
        "origQty": "10.0",
        "stopPrice": "0.2161",
    }


def test_filled_buy_reaches_protected_only_after_exact_exchange_confirmation():
    client = FakeProtectionClient([confirmed_order()])
    flow = LiveProtectionFlow(BinanceSpotProtection(client), live_mode=True)

    result = flow.protect_filled_buy(buy_filled=True, request=request())

    assert result.state is ProtectionState.PROTECTED
    assert result.confirmed is True
    assert result.reason == "EXCHANGE_PROTECTION_CONFIRMED"
    assert len(client.created) == 1


def test_filled_buy_stays_protecting_when_exchange_protection_is_not_confirmed():
    order = confirmed_order()
    order["stopPrice"] = "0.2170"
    client = FakeProtectionClient([order])
    flow = LiveProtectionFlow(BinanceSpotProtection(client), live_mode=True)

    result = flow.protect_filled_buy(buy_filled=True, request=request())

    assert result.state is ProtectionState.PROTECTING
    assert result.confirmed is False
    assert result.reason == "EXCHANGE_PROTECTION_NOT_CONFIRMED"


def test_filled_buy_stays_unprotected_when_protection_submission_fails():
    client = FakeProtectionClient([])
    client.fail_create = True
    flow = LiveProtectionFlow(BinanceSpotProtection(client), live_mode=True)

    result = flow.protect_filled_buy(buy_filled=True, request=request())

    assert result.state is ProtectionState.UNPROTECTED
    assert result.confirmed is False
    assert result.reason.startswith("PROTECTION_SUBMISSION_FAILED:")


def test_filled_buy_stays_protecting_when_confirmation_read_fails():
    client = FakeProtectionClient([])
    client.fail_read = True
    flow = LiveProtectionFlow(BinanceSpotProtection(client), live_mode=True)

    result = flow.protect_filled_buy(buy_filled=True, request=request())

    assert result.state is ProtectionState.PROTECTING
    assert result.confirmed is False
    assert result.reason.startswith("PROTECTION_CONFIRMATION_FAILED:")


def test_unfilled_buy_never_creates_exchange_protection():
    client = FakeProtectionClient([confirmed_order()])
    flow = LiveProtectionFlow(BinanceSpotProtection(client), live_mode=True)

    result = flow.protect_filled_buy(buy_filled=False, request=request())

    assert result.state is ProtectionState.UNPROTECTED
    assert result.confirmed is False
    assert client.created == []


def test_paper_mode_does_not_call_exchange_protection():
    client = FakeProtectionClient([])
    flow = LiveProtectionFlow(BinanceSpotProtection(client), live_mode=False)

    result = flow.protect_filled_buy(buy_filled=True, request=request())

    assert result.state is ProtectionState.PROTECTED
    assert result.confirmed is True
    assert result.reason == "PAPER_MODE_NO_LIVE_PROTECTION_REQUIRED"
    assert client.created == []
