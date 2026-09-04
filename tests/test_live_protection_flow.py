from __future__ import annotations

from core.binance_protection import BinanceSpotProtection, ProtectionRequest
from core.live_protection_flow import LiveProtectionFlow
from core.live_protection_gate import ProtectionState


class FakeClient:
    def __init__(self, *, confirm: bool = True, fail_place: Exception | None = None, fail_read: Exception | None = None):
        self.confirm = confirm
        self.fail_place = fail_place
        self.fail_read = fail_read
        self.calls: list[str] = []

    def create_oco_order(self, **kwargs):
        self.calls.append("place")
        if self.fail_place:
            raise self.fail_place
        return {"orderListId": 99, "orders": []}

    def get_open_orders(self, *, symbol):
        self.calls.append("read")
        if self.fail_read:
            raise self.fail_read
        if not self.confirm:
            return []
        return [{
            "side": "SELL",
            "status": "NEW",
            "type": "STOP_LOSS_LIMIT",
            "origQty": "10",
            "stopPrice": "0.2161",
        }]

    def cancel_order(self, *, symbol, orderId):
        self.calls.append("cancel")
        return {"status": "CANCELED"}


def req() -> ProtectionRequest:
    return ProtectionRequest("ADAUSDT", 10.0, 0.2242, 0.2161, 0.2158)


def test_filled_buy_is_protected_only_after_exchange_confirmation():
    client = FakeClient(confirm=True)
    result = LiveProtectionFlow(BinanceSpotProtection(client), live_mode=True).protect_filled_buy(
        buy_filled=True, request=req()
    )
    assert result.state is ProtectionState.PROTECTED
    assert result.confirmed is True
    assert client.calls == ["place", "read"]


def test_missing_confirmation_never_reports_protected():
    client = FakeClient(confirm=False)
    result = LiveProtectionFlow(BinanceSpotProtection(client), live_mode=True).protect_filled_buy(
        buy_filled=True, request=req()
    )
    assert result.state is ProtectionState.PROTECTING
    assert result.confirmed is False


def test_submission_failure_is_unprotected():
    client = FakeClient(fail_place=RuntimeError("429"))
    result = LiveProtectionFlow(BinanceSpotProtection(client), live_mode=True).protect_filled_buy(
        buy_filled=True, request=req()
    )
    assert result.state is ProtectionState.UNPROTECTED
    assert result.confirmed is False
    assert "PROTECTION_SUBMISSION_FAILED" in result.reason
    assert client.calls == ["place"]


def test_418_submission_failure_is_also_unprotected():
    client = FakeClient(fail_place=RuntimeError("418"))
    result = LiveProtectionFlow(BinanceSpotProtection(client), live_mode=True).protect_filled_buy(
        buy_filled=True, request=req()
    )
    assert result.state is ProtectionState.UNPROTECTED


def test_confirmation_failure_keeps_protecting_state():
    client = FakeClient(fail_read=TimeoutError("timeout"))
    result = LiveProtectionFlow(BinanceSpotProtection(client), live_mode=True).protect_filled_buy(
        buy_filled=True, request=req()
    )
    assert result.state is ProtectionState.PROTECTING
    assert result.confirmed is False


def test_unfilled_buy_does_not_touch_exchange():
    client = FakeClient()
    result = LiveProtectionFlow(BinanceSpotProtection(client), live_mode=True).protect_filled_buy(
        buy_filled=False, request=req()
    )
    assert result.state is ProtectionState.UNPROTECTED
    assert client.calls == []


def test_paper_mode_never_touches_exchange():
    client = FakeClient()
    result = LiveProtectionFlow(BinanceSpotProtection(client), live_mode=False).protect_filled_buy(
        buy_filled=True, request=req()
    )
    assert result.state is ProtectionState.PROTECTED
    assert result.confirmed is True
    assert client.calls == []
