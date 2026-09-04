from __future__ import annotations

from core.binance_protection import BinanceSpotProtection, ProtectionRequest
from core.live_protection_flow import LiveProtectionFlow
from core.live_protection_gate import ProtectionState


def request():
    return ProtectionRequest("ADAUSDT", 10.0, 0.2242, 0.2161, 0.2158)


class FakeClient:
    def __init__(self, *, confirm=True, place_error=None, read_error=None):
        self.confirm = confirm
        self.place_error = place_error
        self.read_error = read_error
        self.calls = []

    def create_oco_order(self, **kwargs):
        self.calls.append("place")
        if self.place_error:
            raise self.place_error
        return {"orderListId": 99}

    def get_open_orders(self, *, symbol):
        self.calls.append("read")
        if self.read_error:
            raise self.read_error
        return ([{"side": "SELL", "status": "NEW", "type": "STOP_LOSS_LIMIT", "origQty": "10", "stopPrice": "0.2161"}] if self.confirm else [])

    def cancel_order(self, *, symbol, orderId):
        return {"status": "CANCELED"}


def run(client, *, filled=True, live=True):
    return LiveProtectionFlow(BinanceSpotProtection(client), live_mode=live).protect_filled_buy(
        buy_filled=filled, request=request()
    )


def test_429_like_submission_failure_is_unprotected():
    client = FakeClient(place_error=RuntimeError("429"))
    result = run(client)
    assert result.state is ProtectionState.UNPROTECTED
    assert result.confirmed is False
    assert client.calls == ["place"]


def test_418_like_submission_failure_is_unprotected():
    client = FakeClient(place_error=RuntimeError("418"))
    result = run(client)
    assert result.state is ProtectionState.UNPROTECTED


def test_confirmation_failure_stays_protecting():
    client = FakeClient(read_error=TimeoutError("timeout"))
    result = run(client)
    assert result.state is ProtectionState.PROTECTING
    assert result.confirmed is False


def test_missing_exchange_order_stays_protecting():
    client = FakeClient(confirm=False)
    result = run(client)
    assert result.state is ProtectionState.PROTECTING


def test_unfilled_buy_does_not_submit_protection():
    client = FakeClient()
    result = run(client, filled=False)
    assert result.state is ProtectionState.UNPROTECTED
    assert client.calls == []


def test_paper_mode_does_not_call_exchange():
    client = FakeClient()
    result = run(client, live=False)
    assert result.state is ProtectionState.PROTECTED
    assert result.confirmed is True
    assert client.calls == []
