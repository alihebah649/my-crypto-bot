"""Real Paper lifecycle regression for symbol-level loss re-entry protection."""
from __future__ import annotations

import importlib

from trade_manager.models import PositionCloseReason, PositionStatus
from trade_manager.risk_manager import PositionExitDecision, PositionExitReason
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


def test_real_stop_loss_closes_position_and_blocks_same_symbol_reentry(monkeypatch, tmp_path):
    """BUY -> STOP LOSS -> CLOSED -> same-symbol BUY must hit cooldown."""
    monkeypatch.setenv("PAPER_STATE_DIR", str(tmp_path / "paper"))
    monkeypatch.setenv("PAPER_INITIAL_CASH", "1000")

    import shadow_main

    shadow_main = importlib.reload(shadow_main)
    runtime = ShadowTradeManagerRuntime(
        initial_cash=1000.0,
        fee_rate=0.001,
        persistence_dir=str(tmp_path / "runtime"),
    )
    runtime.update_market("DOTUSDT", price=100.0, **MARKET)

    shadow_main.runtime = runtime
    shadow_main._original_runtime_open_position = runtime.open_position

    position = runtime.open_position("DOTUSDT", 100.0, 96.0, trade_mode="SCALP")
    assert position is not None
    assert position.status is PositionStatus.OPEN

    decision = PositionExitDecision(
        True,
        PositionExitReason.STOP_LOSS,
        96.0,
        "Forced lifecycle regression stop",
    )
    closed = runtime.facade.execute_decision(position.position_id, decision)

    assert closed is not None
    assert closed.status is PositionStatus.CLOSED
    assert closed.close_reason is PositionCloseReason.STOP_LOSS
    assert closed.realized_pnl < 0.0
    assert any(p.position_id == closed.position_id for p in runtime.repository.get_closed_positions())

    remaining = shadow_main._loss_cooldown("DOTUSDT")
    assert remaining > 0.0

    blocked = shadow_main._open_one_position("DOTUSDT", 95.0, 91.0, "SCALP")
    assert blocked is None
    assert len(runtime.repository.get_open_positions()) == 0


def test_loss_cooldown_remains_symbol_specific(monkeypatch, tmp_path):
    monkeypatch.setenv("PAPER_STATE_DIR", str(tmp_path / "paper"))
    monkeypatch.setenv("PAPER_INITIAL_CASH", "1000")

    import shadow_main

    shadow_main = importlib.reload(shadow_main)
    runtime = ShadowTradeManagerRuntime(
        initial_cash=1000.0,
        fee_rate=0.001,
        persistence_dir=str(tmp_path / "runtime"),
    )
    runtime.update_market("DOTUSDT", price=100.0, **MARKET)
    runtime.update_market("ARBUSDT", price=100.0, **MARKET)
    shadow_main.runtime = runtime
    shadow_main._original_runtime_open_position = runtime.open_position

    position = runtime.open_position("DOTUSDT", 100.0, 96.0, trade_mode="SCALP")
    assert position is not None
    closed = runtime.facade.execute_decision(
        position.position_id,
        PositionExitDecision(True, PositionExitReason.STOP_LOSS, 96.0, "Forced lifecycle regression stop"),
    )
    assert closed is not None and closed.realized_pnl < 0.0

    assert shadow_main._loss_cooldown("DOTUSDT") > 0.0
    assert shadow_main._loss_cooldown("ARBUSDT") == 0.0
