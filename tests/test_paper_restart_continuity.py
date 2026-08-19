"""Restart continuity for the composed Paper Trading runtime."""

import pytest

from trade_manager.models import PositionStatus
from trade_manager.shadow_integration import ShadowTradeManagerRuntime


def test_paper_account_and_position_survive_restart(tmp_path):
    state_dir = str(tmp_path)

    first = ShadowTradeManagerRuntime(
        initial_cash=1000.0,
        fee_rate=0.001,
        persistence_dir=state_dir,
    )
    first.update_market(
        "BTCUSDT",
        price=100.0,
        bid=99.99,
        ask=100.01,
        spread_percent=0.02,
        atr=2.0,
        volume_usdt=1_000_000.0,
        volatility=0.0,
        ema100=90.0,
    )
    position = first.open_position("BTCUSDT", 100.0, 98.0)
    assert position is not None
    assert position.status is PositionStatus.OPEN

    # The current Paper Trading contract targets a $50 notional entry.
    # Entry fee is charged from cash and the position quantity is persisted.
    expected_entry_notional = 50.0
    expected_entry_fee = expected_entry_notional * 0.001
    expected_cash_after_entry = 1000.0 - expected_entry_notional - expected_entry_fee
    assert position.entry_price * position.quantity == pytest.approx(expected_entry_notional)
    assert first.execution_adapter.balance.cash == pytest.approx(expected_cash_after_entry)

    second = ShadowTradeManagerRuntime(
        initial_cash=1000.0,
        fee_rate=0.001,
        persistence_dir=state_dir,
    )

    restored = second.repository.get(position.position_id)
    assert restored is not None
    assert restored.status is PositionStatus.OPEN
    assert restored.quantity == pytest.approx(position.quantity)
    assert restored.entry_price == pytest.approx(position.entry_price)
    assert second.execution_adapter.balance.cash == pytest.approx(expected_cash_after_entry)
    assert second.execution_adapter.balance.assets["BTCUSDT"] == pytest.approx(position.quantity)

    # The restored runtime can continue the lifecycle without duplicating the
    # position or resetting the paper account.
    second.update_market(
        "BTCUSDT",
        price=103.0,
        bid=102.99,
        ask=103.01,
        spread_percent=0.02,
        atr=2.0,
        volume_usdt=1_000_000.0,
        volatility=0.0,
        ema100=90.0,
    )
    closed = second.facade.close_position(position.position_id, 103.0)
    assert closed is not None
    assert closed.status is PositionStatus.CLOSED
    assert second.execution_adapter.balance.assets.get("BTCUSDT", 0.0) == pytest.approx(0.0)

    expected_exit_notional = expected_entry_notional * 1.03
    expected_exit_fee = expected_exit_notional * 0.001
    expected_final_cash = expected_cash_after_entry + expected_exit_notional - expected_exit_fee
    assert second.execution_adapter.balance.cash == pytest.approx(expected_final_cash)
