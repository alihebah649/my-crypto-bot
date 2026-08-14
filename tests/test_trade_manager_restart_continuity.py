"""Restart continuity tests for the Paper Trading baseline."""

from __future__ import annotations

from trade_manager.shadow_integration import ShadowTradeManagerRuntime


def market(price: float, ema100: float = 90.0) -> dict:
    return {
        "price": price,
        "bid": price - 0.01,
        "ask": price + 0.01,
        "spread_percent": 0.02,
        "atr": 2.0,
        "volume_usdt": 1_000_000.0,
        "volatility": 0.02,
        "ema100": ema100,
    }


def test_open_position_and_paper_balance_survive_runtime_restart(tmp_path):
    state_dir = str(tmp_path / "trade_manager")

    first = ShadowTradeManagerRuntime(
        initial_cash=1000.0,
        fee_rate=0.001,
        state_dir=state_dir,
    )
    first.update_market("BTCUSDT", **market(100.0))
    position = first.open_position("BTCUSDT", 100.0, 96.0)
    assert position is not None
    quantity = position.quantity
    cash_after_buy = first.execution_adapter.balance.cash

    second = ShadowTradeManagerRuntime(
        initial_cash=1000.0,
        fee_rate=0.001,
        state_dir=state_dir,
    )

    restored = second.repository.get(position.position_id)
    assert restored is not None
    assert restored.symbol == "BTCUSDT"
    assert restored.quantity == quantity
    assert restored.status.name == "OPEN"
    assert second.execution_adapter.balance.assets["BTCUSDT"] == quantity
    assert second.execution_adapter.balance.cash == cash_after_buy


def test_closed_position_and_balance_are_restored_without_double_counting(tmp_path):
    state_dir = str(tmp_path / "trade_manager")

    first = ShadowTradeManagerRuntime(
        initial_cash=1000.0,
        fee_rate=0.001,
        state_dir=state_dir,
    )
    first.update_market("BTCUSDT", **market(100.0))
    position = first.open_position("BTCUSDT", 100.0, 96.0)
    assert position is not None

    first.update_market("BTCUSDT", **market(110.0))
    closed = first.facade.close_position(position.position_id, 110.0)
    assert closed is not None
    assert closed.status.name == "CLOSED"
    realized = closed.realized_pnl
    cash_after_close = first.execution_adapter.balance.cash

    second = ShadowTradeManagerRuntime(
        initial_cash=1000.0,
        fee_rate=0.001,
        state_dir=state_dir,
    )
    restored = second.repository.get(position.position_id)

    assert restored is not None
    assert restored.status.name == "CLOSED"
    assert restored.realized_pnl == realized
    assert second.execution_adapter.balance.assets.get("BTCUSDT", 0.0) == 0.0
    assert second.execution_adapter.balance.cash == cash_after_close
    assert second.loss_tracker.snapshot().daily_pnl == realized
