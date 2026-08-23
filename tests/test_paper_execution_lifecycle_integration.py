"""End-to-end Paper Trading execution/ownership lifecycle contracts."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.execution_models import OrderStatus
from trade_manager.models import PositionStatus
from trade_manager.shadow_integration import ShadowTradeManagerRuntime


MARKET = dict(
    bid=99.99,
    ask=100.01,
    spread_percent=0.02,
    atr=2.0,
    volume_usdt=1_000_000.0,
    volatility=0.02,
    ema100=90.0,
)


def build_runtime() -> ShadowTradeManagerRuntime:
    runtime = ShadowTradeManagerRuntime(initial_cash=1000.0, fee_rate=0.001)
    runtime.update_market("BTCUSDT", price=100.0, **MARKET)
    return runtime


def test_buy_then_successful_sell_closes_position_and_realizes_pnl():
    runtime = build_runtime()
    position = runtime.open_position("BTCUSDT", 100.0, 96.0)
    assert position is not None
    quantity = position.quantity
    assert runtime.execution_adapter.balance.assets["BTCUSDT"] == pytest.approx(quantity)

    closed = runtime.facade.close_position(position.position_id, 110.0)

    assert closed is not None
    assert closed.status is PositionStatus.CLOSED
    assert closed.realized_pnl > 0.0
    assert runtime.execution_adapter.balance.assets.get("BTCUSDT", 0.0) == pytest.approx(0.0)


def test_failed_sell_preserves_owned_position_and_does_not_create_closed_pnl():
    runtime = build_runtime()
    position = runtime.open_position("BTCUSDT", 100.0, 96.0)
    assert position is not None
    quantity = position.quantity
    original_realized_pnl = position.realized_pnl
    original_status = position.status
    assert runtime.execution_adapter.balance.assets["BTCUSDT"] == pytest.approx(quantity)

    def rejected_sell(_request):
        return SimpleNamespace(
            status=OrderStatus.REJECTED,
            symbol="BTCUSDT",
            executed_quantity=0.0,
            average_price=0.0,
            exchange_order_id=None,
            client_order_id=None,
            fees=SimpleNamespace(total=0.0),
            message="forced paper sell rejection",
        )

    runtime.execution_adapter.execute = rejected_sell

    closed = runtime.facade.close_position(position.position_id, 90.0)
    stored = runtime.repository.get(position.position_id)

    assert closed is None
    assert stored is not None
    assert stored.status is original_status is PositionStatus.OPEN
    assert stored.quantity == pytest.approx(quantity)
    assert stored.realized_pnl == pytest.approx(original_realized_pnl)
    assert runtime.execution_adapter.balance.assets["BTCUSDT"] == pytest.approx(quantity)


def test_partial_sell_keeps_remaining_owned_quantity_open():
    runtime = build_runtime()
    position = runtime.open_position("BTCUSDT", 100.0, 96.0)
    assert position is not None
    original_quantity = position.quantity

    original_execute = runtime.execution_adapter.execute

    def partial_sell(request):
        result = original_execute(request)
        result.executed_quantity = request.quantity / 2.0
        result.remaining_quantity = request.quantity - result.executed_quantity
        result.status = OrderStatus.PARTIALLY_FILLED
        runtime.execution_adapter.balance.assets["BTCUSDT"] = original_quantity - result.executed_quantity
        return result

    runtime.execution_adapter.execute = partial_sell

    result = runtime.facade.close_position(position.position_id, 105.0)
    stored = runtime.repository.get(position.position_id)

    assert result is not None
    assert stored is not None
    assert stored.status is PositionStatus.OPEN
    assert stored.quantity == pytest.approx(original_quantity / 2.0)
    assert runtime.execution_adapter.balance.assets["BTCUSDT"] == pytest.approx(original_quantity / 2.0)
    assert stored.realized_pnl == pytest.approx(0.0)
