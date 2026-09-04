from __future__ import annotations

from core.binance_protection import BinanceSpotProtection, ProtectionRequest
from core.binance_reconciliation import LocalPositionView
from core.live_protection_flow import LiveProtectionFlow
from core.live_protection_gate import ProtectionState
from core.live_startup_coordinator import LiveStartupCoordinator


REQUEST = ProtectionRequest(
    symbol="ADAUSDT",
    quantity=10.0,
    take_profit_price=0.2240,
    stop_price=0.2161,
    stop_limit_price=0.2159,
)


class FakeExchange:
    """Small exchange state machine shared across the simulated restart."""

    def __init__(self) -> None:
        self.balances = []
        self.orders: dict[str, list[dict[str, str]]] = {}
        self.connected = False

    def create_oco_order(self, **kwargs):
        symbol = kwargs["symbol"].upper()
        quantity = str(kwargs["quantity"])
        stop_price = str(kwargs["stopPrice"])
        self.orders[symbol] = [
            {
                "symbol": symbol,
                "side": "SELL",
                "status": "NEW",
                "type": "STOP_LOSS_LIMIT",
                "origQty": quantity,
                "stopPrice": stop_price,
            }
        ]
        return {"orderListId": 101, "symbol": symbol, "status": "EXECUTING"}

    def get_open_orders(self, *, symbol: str):
        return list(self.orders.get(symbol.upper(), []))

    def cancel_order(self, *, symbol: str, orderId):
        return {"symbol": symbol.upper(), "orderId": orderId, "status": "CANCELED"}

    def connect(self):
        self.connected = True

    def get_account_snapshot(self):
        return {"balances": self.balances}

    def get_open_orders_snapshot(self, symbol: str):
        return self.get_open_orders(symbol=symbol)


def local_position(*, quantity: float = 10.0, stop_price: float = 0.2161):
    return LocalPositionView("ADAUSDT", quantity, "p1", stop_price)


def fund_exchange(exchange: FakeExchange, quantity: float = 10.0):
    exchange.balances = [
        {"asset": "ADA", "free": str(quantity), "locked": "0"}
    ]


def test_protected_buy_survives_restart_and_allows_resume():
    exchange = FakeExchange()
    fund_exchange(exchange)

    protection = BinanceSpotProtection(exchange)
    flow = LiveProtectionFlow(protection, live_mode=True)
    protected = flow.protect_filled_buy(buy_filled=True, request=REQUEST)

    assert protected.state is ProtectionState.PROTECTED
    assert protected.confirmed is True

    # Simulate a process restart: reconstruct the local position from durable state.
    restarted_local_position = local_position()
    result = LiveStartupCoordinator(exchange, ["ADAUSDT"]).start(
        [restarted_local_position]
    )

    assert result.decision.allowed is True
    assert result.decision.reason == "RECONCILIATION_SAFE"
    assert result.reconciliation.has_unprotected is False
    assert result.reconciliation.has_orphans is False


def test_restart_blocks_when_exchange_protection_stop_changed():
    exchange = FakeExchange()
    fund_exchange(exchange)
    exchange.orders["ADAUSDT"] = [
        {
            "symbol": "ADAUSDT",
            "side": "SELL",
            "status": "NEW",
            "type": "STOP_LOSS_LIMIT",
            "origQty": "10.0",
            "stopPrice": "0.2170",
        }
    ]

    result = LiveStartupCoordinator(exchange, ["ADAUSDT"]).start([local_position()])

    assert result.decision.allowed is False
    assert result.decision.reason == "RECONCILIATION_BLOCKED"
    assert result.reconciliation.has_unprotected is True


def test_restart_blocks_orphan_exchange_position():
    exchange = FakeExchange()
    fund_exchange(exchange)
    exchange.orders["ADAUSDT"] = [
        {
            "symbol": "ADAUSDT",
            "side": "SELL",
            "status": "NEW",
            "type": "STOP_LOSS_LIMIT",
            "origQty": "10.0",
            "stopPrice": "0.2161",
        }
    ]

    result = LiveStartupCoordinator(exchange, ["ADAUSDT"]).start([])

    assert result.decision.allowed is False
    assert result.decision.reason == "RECONCILIATION_BLOCKED"
    assert result.reconciliation.has_orphans is True


def test_restart_blocks_when_exchange_quantity_changed():
    exchange = FakeExchange()
    fund_exchange(exchange, quantity=9.0)
    exchange.orders["ADAUSDT"] = [
        {
            "symbol": "ADAUSDT",
            "side": "SELL",
            "status": "NEW",
            "type": "STOP_LOSS_LIMIT",
            "origQty": "9.0",
            "stopPrice": "0.2161",
        }
    ]

    result = LiveStartupCoordinator(exchange, ["ADAUSDT"]).start([local_position()])

    assert result.decision.allowed is False
    assert result.decision.reason == "RECONCILIATION_BLOCKED"
    assert result.reconciliation.has_unprotected is True
