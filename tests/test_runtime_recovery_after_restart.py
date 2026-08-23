from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from core.execution_models import OrderStatus
from trade_manager.models import PositionStatus
from trade_manager.shadow_integration import ShadowTradeManagerRuntime


MARKET = dict(bid=99.99, ask=100.01, spread_percent=0.02, atr=2.0, volume_usdt=1_000_000.0, volatility=0.02, ema100=90.0)


def build_runtime(path: Path) -> ShadowTradeManagerRuntime:
    runtime = ShadowTradeManagerRuntime(initial_cash=1000.0, fee_rate=0.001, persistence_dir=str(path))
    runtime.update_market("BTCUSDT", price=100.0, **MARKET)
    return runtime


def test_runtime_restart_restores_open_position_and_can_continue_exit(tmp_path: Path):
    runtime1 = build_runtime(tmp_path)
    position = runtime1.open_position("BTCUSDT", 100.0, 96.0)
    assert position is not None

    runtime2 = build_runtime(tmp_path)
    restored = runtime2.repository.get(position.position_id)
    assert restored is not None
    assert restored.status is PositionStatus.OPEN
    assert restored.quantity > 0

    runtime2.execution_adapter.market_prices["BTCUSDT"] = 110.0
    closed = runtime2.facade.close_position(restored.position_id, 110.0)

    assert closed is not None
    assert closed.status is PositionStatus.CLOSED
    assert closed.realized_pnl > 0.0
    assert runtime2.execution_adapter.balance.assets.get("BTCUSDT", 0.0) == pytest.approx(0.0)


def test_failed_exit_after_restart_preserves_position_and_ownership(tmp_path: Path):
    runtime1 = build_runtime(tmp_path)
    position = runtime1.open_position("BTCUSDT", 100.0, 96.0)
    assert position is not None

    runtime2 = build_runtime(tmp_path)
    restored = runtime2.repository.get(position.position_id)
    assert restored is not None
    owned_before = runtime2.execution_adapter.balance.assets.get("BTCUSDT", 0.0)
    original_pnl = restored.realized_pnl

    def rejected_sell(_request):
        return SimpleNamespace(status=OrderStatus.REJECTED, symbol="BTCUSDT", executed_quantity=0.0,
                               average_price=0.0, exchange_order_id=None, client_order_id=None,
                               fees=SimpleNamespace(total=0.0), message="forced paper sell rejection after restart")

    runtime2.execution_adapter.execute = rejected_sell
    closed = runtime2.facade.close_position(restored.position_id, 110.0)
    final = runtime2.repository.get(restored.position_id)

    assert closed is None
    assert final is not None
    assert final.status is PositionStatus.OPEN
    assert final.quantity == pytest.approx(restored.quantity)
    assert final.realized_pnl == pytest.approx(original_pnl)
    assert runtime2.execution_adapter.balance.assets.get("BTCUSDT", 0.0) == pytest.approx(owned_before)
