from __future__ import annotations

import re

import pytest

from core.binance_reconciliation import LocalPositionView
from core.execution_exceptions import ExchangeConnectionError, ExchangeError
from core.live_startup_coordinator import LiveStartupCoordinator


class FakeAdapter:
    def __init__(self, balances, orders, *, connect_error=None, account_error=None, orders_error=None):
        self.balances = balances
        self.orders = orders
        self.connect_error = connect_error
        self.account_error = account_error
        self.orders_error = orders_error
        self.connected = False
        self.calls = []

    def connect(self):
        self.calls.append("connect")
        if self.connect_error:
            raise self.connect_error
        self.connected = True

    def get_account_snapshot(self):
        self.calls.append("account")
        if self.account_error:
            raise self.account_error
        return {"balances": self.balances}

    def get_open_orders_snapshot(self, symbol):
        self.calls.append(("orders", symbol))
        if self.orders_error:
            raise self.orders_error
        return list(self.orders.get(symbol.upper(), []))


def position(stop_price=0.2161, quantity=10.0):
    return LocalPositionView("ADAUSDT", quantity, "p1", stop_price)


def protection(*, stop_price="0.2161", quantity="10", order_type="STOP_LOSS_LIMIT", status="NEW"):
    return {
        "side": "SELL", "status": status, "type": order_type,
        "origQty": quantity, "stopPrice": stop_price,
    }


def adapter_with_position(order=None):
    return FakeAdapter(
        [{"asset": "ADA", "free": "10", "locked": "0"}],
        {"ADAUSDT": [order or protection()]},
    )


def test_live_startup_allows_resume_only_after_safe_reconciliation():
    adapter = adapter_with_position()
    result = LiveStartupCoordinator(adapter, ["ADAUSDT"]).start([position()])
    assert result.decision.allowed is True
    assert result.decision.reason == "RECONCILIATION_SAFE"
    assert adapter.calls == ["connect", "account", ("orders", "ADAUSDT")]


def test_live_startup_blocks_when_exchange_position_is_orphan():
    adapter = FakeAdapter(
        [{"asset": "ADA", "free": "10", "locked": "0"}],
        {},
    )
    result = LiveStartupCoordinator(adapter, ["ADAUSDT"]).start([])
    assert result.decision.allowed is False
    assert result.decision.reason == "RECONCILIATION_BLOCKED"
    assert result.reconciliation.has_orphans is True
    assert adapter.calls == ["connect", "account"]


def test_live_startup_blocks_when_protection_stop_does_not_match():
    adapter = adapter_with_position(protection(stop_price="0.2170"))
    result = LiveStartupCoordinator(adapter, ["ADAUSDT"]).start([position()])
    assert result.decision.allowed is False
    assert result.reconciliation.has_unprotected is True


def test_live_startup_blocks_when_protection_quantity_does_not_match():
    adapter = adapter_with_position(protection(quantity="9"))
    result = LiveStartupCoordinator(adapter, ["ADAUSDT"]).start([position()])
    assert result.decision.allowed is False
    assert result.reconciliation.has_unprotected is True


def test_live_startup_blocks_when_protection_type_is_take_profit_only():
    adapter = adapter_with_position(protection(order_type="TAKE_PROFIT_LIMIT"))
    result = LiveStartupCoordinator(adapter, ["ADAUSDT"]).start([position()])
    assert result.decision.allowed is False
    assert result.reconciliation.has_unprotected is True


def test_live_startup_accepts_partially_filled_stop_protection():
    adapter = adapter_with_position(protection(status="PARTIALLY_FILLED"))
    result = LiveStartupCoordinator(adapter, ["ADAUSDT"]).start([position()])
    assert result.decision.allowed is True


def test_live_startup_accepts_quantity_within_tolerance():
    adapter = adapter_with_position(protection(quantity="10.000000005"))
    result = LiveStartupCoordinator(adapter, ["ADAUSDT"]).start([position()])
    assert result.decision.allowed is True


def test_live_startup_blocks_when_local_position_is_missing_on_exchange():
    adapter = FakeAdapter([], {"ADAUSDT": [protection()]})
    result = LiveStartupCoordinator(adapter, ["ADAUSDT"]).start([position()])
    assert result.decision.allowed is False
    assert any(i.code == "LOCAL_POSITION_MISSING_ON_EXCHANGE" for i in result.reconciliation.issues)


@pytest.mark.parametrize("error", [ExchangeConnectionError("418 banned"), ExchangeError("429 rate limited")])
def test_live_startup_does_not_resume_when_binance_account_read_fails(error):
    adapter = FakeAdapter([], {}, account_error=error)
    with pytest.raises(type(error), match=re.escape(str(error))):
        LiveStartupCoordinator(adapter, ["ADAUSDT"]).start([])
    assert adapter.calls == ["connect", "account"]


@pytest.mark.parametrize("error", [ExchangeConnectionError("418 banned"), ExchangeError("429 rate limited")])
def test_live_startup_does_not_resume_when_binance_order_read_fails(error):
    adapter = FakeAdapter([], {}, orders_error=error)
    with pytest.raises(type(error), match=re.escape(str(error))):
        LiveStartupCoordinator(adapter, ["ADAUSDT"]).start([position()])
    assert adapter.calls == ["connect", "account", ("orders", "ADAUSDT")]
