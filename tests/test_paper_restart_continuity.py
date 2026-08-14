"""Restart/state-continuity contract for the Paper Trading baseline."""
from __future__ import annotations

from pathlib import Path

from trade_manager.shadow_integration import ShadowTradeManagerRuntime


def _market(runtime: ShadowTradeManagerRuntime, price: float) -> None:
    runtime.update_market(
        "BTCUSDT",
        price=price,
        bid=price - 0.01,
        ask=price + 0.01,
        spread_percent=0.02,
        atr=2.0,
        volume_usdt=1_000_000.0,
        volatility=0.02,
        ema100=90.0,
    )


def test_open_position_and_paper_balance_survive_restart(tmp_path: Path):
    state_dir = str(tmp_path / "paper-state")

    first = ShadowTradeManagerRuntime(
        initial_cash=1000.0,
        fee_rate=0.001,
        persistence_dir=state_dir,
    )
    _market(first, 100.0)
    position = first.open_position("BTCUSDT", 100.0, 96.0)
    assert position is not None

    original_id = position.position_id
    original_quantity = position.quantity
    original_cash = first.execution_adapter.balance.cash

    second = ShadowTradeManagerRuntime(
        initial_cash=1000.0,
        fee_rate=0.001,
        persistence_dir=state_dir,
    )
    restored = second.repository.get(original_id)

    assert restored is not None
    assert restored.quantity == original_quantity
    assert restored.entry_price == position.entry_price
    assert restored.status.name == "OPEN"
    assert second.execution_adapter.balance.cash == original_cash
    assert second.execution_adapter.balance.assets["BTCUSDT"] == original_quantity

    _market(second, 101.0)
    assert second.execution_adapter.get_market_price("BTCUSDT") == 101.0
