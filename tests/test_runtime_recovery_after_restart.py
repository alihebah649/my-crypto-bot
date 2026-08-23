from __future__ import annotations

from pathlib import Path

from trade_manager.models import PositionStatus
from trade_manager.shadow_integration import ShadowTradeManagerRuntime


def test_runtime_restart_restores_open_position_and_re_evaluates_it(tmp_path: Path):
    runtime1 = ShadowTradeManagerRuntime(persistence_dir=str(tmp_path))
    runtime1.update_market("BTCUSDT", price=100.0, atr=1.0, ema100=90.0)
    position = runtime1.open_position("BTCUSDT", entry_price=100.0, stop_loss=96.0)
    assert position is not None

    runtime2 = ShadowTradeManagerRuntime(persistence_dir=str(tmp_path))
    restored = runtime2.repository.get(position.position_id)
    assert restored is not None
    assert restored.status is PositionStatus.OPEN
    assert restored.quantity > 0

    runtime2.update_market("BTCUSDT", price=110.0, atr=1.0, ema100=90.0)
    result = runtime2.run_exit_watchdog()
    final = runtime2.repository.get(position.position_id)

    assert result.evaluated >= 1
    assert final is not None
    assert final.status in {PositionStatus.OPEN, PositionStatus.HOLD, PositionStatus.CLOSED}


def test_failed_exit_after_restart_preserves_position_and_ownership(tmp_path: Path):
    runtime1 = ShadowTradeManagerRuntime(persistence_dir=str(tmp_path))
    runtime1.update_market("BTCUSDT", price=100.0, atr=1.0, ema100=90.0)
    position = runtime1.open_position("BTCUSDT", entry_price=100.0, stop_loss=96.0)
    assert position is not None

    runtime2 = ShadowTradeManagerRuntime(persistence_dir=str(tmp_path))
    restored = runtime2.repository.get(position.position_id)
    assert restored is not None
    owned_before = runtime2.execution_adapter.balance.assets.get("BTCUSDT", 0.0)

    original = runtime2.execution_gateway.execute

    def rejected(request):
        outcome = original(request)
        outcome.success = False
        outcome.executed_quantity = 0.0
        return outcome

    runtime2.execution_gateway.execute = rejected
    runtime2.update_market("BTCUSDT", price=110.0, atr=1.0, ema100=90.0)
    runtime2.run_exit_watchdog()

    final = runtime2.repository.get(position.position_id)
    assert final is not None
    assert final.status is not PositionStatus.CLOSED
    assert runtime2.execution_adapter.balance.assets.get("BTCUSDT", 0.0) == owned_before
    assert final.realized_pnl == 0.0
