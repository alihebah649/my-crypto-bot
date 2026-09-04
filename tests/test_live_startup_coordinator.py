from __future__ import annotations

from core.binance_reconciliation import LocalPositionView
from core.live_startup_coordinator import LiveStartupCoordinator


class FakeAdapter:
    def __init__(self, balances, orders):
        self.balances = balances
        self.orders = orders
        self.connected = False
        self.calls = []

    def connect(self):
        self.calls.append("connect")
        self.connected = True

    def get_account(self):
        self.calls.append("account")
        return {"balances": self.balances}

    def get_open_orders(self, *, symbol):
        self.calls.append(("orders", symbol))
        return list(self.orders.get(symbol, []))


def position(stop_price=0.2161):
    return LocalPositionView("ADAUSDT", 10.0, "p1", stop_price)


def protection():
    return {
        "side": "SELL", "status": "NEW", "type": "STOP_LOSS_LIMIT",
        "origQty": "10", "stopPrice": "0.2161",
    }


def test_live_startup_allows_resume_only_after_safe_reconciliation():
    adapter = FakeAdapter(
        [{"asset": "ADA", "free": "10", "locked": "0"}],
        {"ADAUSDT": [protection()]},
    )
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


def test_live_startup_blocks_when_protection_stop_does_not_match():
    adapter = FakeAdapter(
        [{"asset": "ADA", "free": "10", "locked": "0"}],
        {"ADAUSDT": [{**protection(), "stopPrice": "0.2170"}]},
    )
    result = LiveStartupCoordinator(adapter, ["ADAUSDT"]).start([position()])
    assert result.decision.allowed is False
    assert result.reconciliation.has_unprotected is True
