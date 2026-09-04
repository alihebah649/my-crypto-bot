from __future__ import annotations

from core.binance_reconciliation import LocalPositionView
from core.binance_startup_reconciliation import BinanceStartupReconciliation


class FakeClient:
    def __init__(self, balances, orders_by_symbol):
        self.balances = balances
        self.orders_by_symbol = orders_by_symbol
        self.calls = []

    def get_account(self):
        self.calls.append("account")
        return {"balances": self.balances}

    def get_open_orders(self, *, symbol):
        self.calls.append(("orders", symbol))
        return list(self.orders_by_symbol.get(symbol, []))


def protection_order(qty="10", stop="0.2161"):
    return {
        "side": "SELL", "status": "NEW", "type": "STOP_LOSS_LIMIT",
        "origQty": qty, "stopPrice": stop,
    }


def position(symbol="ADAUSDT", quantity=10.0):
    return LocalPositionView(symbol=symbol, quantity=quantity, position_id="p1")


def test_matching_exchange_position_and_protection_is_safe():
    client = FakeClient(
        [{"asset": "ADA", "free": "10", "locked": "0"}],
        {"ADAUSDT": [protection_order()]},
    )
    snapshot = BinanceStartupReconciliation(client).reconcile([position()])
    assert snapshot.result.safe_to_resume is True
    assert snapshot.result.issues == ()
    assert client.calls == ["account", ("orders", "ADAUSDT")]


def test_exchange_asset_without_local_position_blocks_as_orphan():
    client = FakeClient(
        [{"asset": "ADA", "free": "10", "locked": "0"}],
        {},
    )
    snapshot = BinanceStartupReconciliation(client).reconcile([])
    assert snapshot.result.safe_to_resume is False
    assert snapshot.result.has_orphans is True
    assert snapshot.result.issues[0].symbol == "ADAUSDT"


def test_local_position_missing_exchange_balance_blocks():
    client = FakeClient([], {"ADAUSDT": [protection_order()]})
    snapshot = BinanceStartupReconciliation(client).reconcile([position()])
    assert snapshot.result.safe_to_resume is False
    assert snapshot.result.issues[0].code == "LOCAL_POSITION_MISSING_ON_EXCHANGE"


def test_local_position_without_protection_blocks():
    client = FakeClient(
        [{"asset": "ADA", "free": "10", "locked": "0"}],
        {"ADAUSDT": []},
    )
    snapshot = BinanceStartupReconciliation(client).reconcile([position()])
    assert snapshot.result.safe_to_resume is False
    assert snapshot.result.has_unprotected is True


def test_dust_balance_does_not_create_orphan():
    client = FakeClient(
        [{"asset": "ADA", "free": "0.0000000000001", "locked": "0"}],
        {},
    )
    snapshot = BinanceStartupReconciliation(client).reconcile([])
    assert snapshot.result.safe_to_resume is True
    assert snapshot.result.issues == ()


def test_locked_balance_counts_as_owned_quantity():
    client = FakeClient(
        [{"asset": "ADA", "free": "4", "locked": "6"}],
        {"ADAUSDT": [protection_order()]},
    )
    snapshot = BinanceStartupReconciliation(client).reconcile([position()])
    assert snapshot.result.safe_to_resume is True
    assert snapshot.exchange_assets[0].quantity == 10.0
