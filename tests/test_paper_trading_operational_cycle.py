"""Full operational Paper Trading cycle.

The test follows the application boundary used by ``shadow_main.py``:
market state -> signal -> Part-6 risk -> Trade Manager -> core paper fill
-> Smart Hold/Recovery -> recovery -> exit -> P&L/accounting -> persistence.

No exchange credentials or live orders are used.
"""

import pytest

from trade_manager.models import PositionStatus
from trade_manager.shadow_integration import ShadowTradeManagerRuntime


def market(runtime: ShadowTradeManagerRuntime, symbol: str, price: float, *, ema: float = 90.0, atr: float = 2.0) -> None:
    runtime.update_market(
        symbol,
        price=price,
        bid=price - 0.01,
        ask=price + 0.01,
        spread_percent=0.02,
        atr=atr,
        volume_usdt=1_000_000.0,
        volatility=0.0,
        ema100=ema,
    )


def test_full_paper_operational_cycle(tmp_path):
    runtime = ShadowTradeManagerRuntime(
        initial_cash=1000.0,
        fee_rate=0.001,
        persistence_dir=str(tmp_path),
    )

    # 1) Market data reaches the composed runtime and is available to risk/TM.
    market(runtime, "BTCUSDT", 100.0)
    assert runtime.market.price["BTCUSDT"] == pytest.approx(100.0)
    assert runtime.market.ema100["BTCUSDT"] == pytest.approx(90.0)
    assert runtime.market.atr["BTCUSDT"] == pytest.approx(2.0)

    # 2) Signal layer produces the expected BUY decision from the current
    # application signal rule. The runtime then sends the entry through Part 6.
    from shadow_main import evaluate_signal

    signal = evaluate_signal(100.0, 90.0, 30.0)
    assert signal == "BUY"

    # 3) Part-6 risk approval -> Trade Manager -> Core Paper Execution.
    position = runtime.open_position("BTCUSDT", 100.0, 98.0)
    assert position is not None
    assert position.status is PositionStatus.OPEN
    assert position.quantity == pytest.approx(5.0)
    assert runtime.execution_adapter.balance.assets["BTCUSDT"] == pytest.approx(5.0)
    assert runtime.execution_adapter.balance.cash == pytest.approx(499.5)

    # 4) Adverse move: Smart Hold/Recovery must retain ownership instead of
    # immediately selling a modest loss when recovery conditions are healthy.
    market(runtime, "BTCUSDT", 98.5, ema=90.0)
    runtime.evaluate_position("BTCUSDT")
    held = runtime.repository.get(position.position_id)
    assert held is not None
    assert held.status is PositionStatus.HOLD
    assert held.hold_reason
    assert runtime.execution_adapter.balance.assets["BTCUSDT"] == pytest.approx(5.0)

    # 5) Recovery: once sufficiently profitable, HOLD returns to OPEN and the
    # Part-8 break-even protection can activate without forcing a sale.
    market(runtime, "BTCUSDT", 102.0, ema=90.0)
    runtime.evaluate_position("BTCUSDT")
    recovered = runtime.repository.get(position.position_id)
    assert recovered is not None
    assert recovered.status is PositionStatus.OPEN
    assert recovered.current_price == pytest.approx(102.0)
    assert recovered.metadata.get("break_even_activated") is True

    # 6) Explicit exit after recovery -> first update the paper market to the
    # intended fill price, then Core Paper SELL -> Trade Manager close state ->
    # realized P&L and fee accounting.
    market(runtime, "BTCUSDT", 103.0, ema=90.0)
    closed = runtime.facade.close_position(position.position_id, 103.0)
    assert closed is not None
    assert closed.status is PositionStatus.CLOSED
    assert closed.realized_pnl == pytest.approx(13.985)
    assert closed.total_fees == pytest.approx(1.015)
    assert runtime.execution_adapter.balance.assets["BTCUSDT"] == pytest.approx(0.0)
    assert runtime.execution_adapter.balance.cash == pytest.approx(1013.985)

    # 7) Accounting survives the lifecycle and the closed position is retained.
    assert runtime.loss_tracker.snapshot().daily_pnl == pytest.approx(13.985)
    assert len(runtime.repository.get_closed_positions()) == 1

    # 8) Restart continuity: position and paper account remain consistent.
    restarted = ShadowTradeManagerRuntime(
        initial_cash=1000.0,
        fee_rate=0.001,
        persistence_dir=str(tmp_path),
    )
    restored = restarted.repository.get(position.position_id)
    assert restored is not None
    assert restored.status is PositionStatus.CLOSED
    assert restored.realized_pnl == pytest.approx(13.985)
    assert restarted.execution_adapter.balance.cash == pytest.approx(1013.985)
    assert restarted.execution_adapter.balance.assets.get("BTCUSDT", 0.0) == pytest.approx(0.0)


def test_operational_cycle_risk_blocks_bad_market_before_execution(tmp_path):
    runtime = ShadowTradeManagerRuntime(
        initial_cash=1000.0,
        fee_rate=0.001,
        persistence_dir=str(tmp_path),
    )

    # Below Part-6 minimum volume: the market is present, but the risk gate
    # must reject before the paper broker receives a BUY.
    market(runtime, "ETHUSDT", 100.0)
    runtime.market.volume_usdt["ETHUSDT"] = 100_000.0

    position = runtime.open_position("ETHUSDT", 100.0, 98.0)
    assert position is None
    assert runtime.repository.get_open_positions() == []
    assert runtime.execution_adapter.balance.assets == {}
    assert runtime.execution_adapter.balance.cash == pytest.approx(1000.0)


def test_operational_cycle_failed_exit_preserves_owned_position(tmp_path):
    runtime = ShadowTradeManagerRuntime(
        initial_cash=1000.0,
        fee_rate=0.001,
        persistence_dir=str(tmp_path),
    )
    market(runtime, "SOLUSDT", 100.0)
    position = runtime.open_position("SOLUSDT", 100.0, 98.0)
    assert position is not None

    # Simulate an execution-side failure: the paper adapter no longer owns the
    # asset even though Trade Manager still records the position.
    runtime.execution_adapter.balance.assets["SOLUSDT"] = 0.0
    market(runtime, "SOLUSDT", 103.0)

    closed = runtime.facade.close_position(position.position_id, 103.0)
    assert closed is None
    stored = runtime.repository.get(position.position_id)
    assert stored is not None
    assert stored.status is PositionStatus.OPEN
    assert runtime.execution_adapter.balance.cash == pytest.approx(499.5)
