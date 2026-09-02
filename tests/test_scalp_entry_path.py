from __future__ import annotations

import pytest

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


def test_scalp_buy_crosses_runtime_risk_facade_and_execution():
    runtime = ShadowTradeManagerRuntime(initial_cash=1000.0, fee_rate=0.001)
    runtime.update_market("FETUSDT", price=100.0, **MARKET)

    position = runtime.open_position(
        "FETUSDT",
        entry_price=100.0,
        stop_loss=96.0,
        trade_mode="SCALP",
    )

    assert position is not None
    assert position.status is PositionStatus.OPEN
    assert position.quantity == pytest.approx(0.5)
    assert position.entry_metadata["trade_mode"] == "SCALP"

    trace = runtime.last_entry_diagnostics["FETUSDT"]
    assert trace["trade_mode"] == "SCALP"
    assert trace["risk_gateway"] == "PASS"
    assert trace["facade"] == "CALLED"
    assert trace["execution"] == "FILLED"
    assert trace["result"] == "POSITION_OPENED"
    assert runtime.execution_adapter.balance.assets["FETUSDT"] == pytest.approx(0.5)


def test_scalp_lane_does_not_fall_back_to_swing_when_trade_mode_is_explicit():
    runtime = ShadowTradeManagerRuntime(initial_cash=1000.0, fee_rate=0.001)
    runtime.update_market("FETUSDT", price=100.0, **MARKET)

    position = runtime.open_position(
        "FETUSDT",
        entry_price=100.0,
        stop_loss=96.0,
        trade_mode="SCALP",
    )

    assert position is not None
    assert position.entry_metadata.get("trade_mode") == "SCALP"
    assert position.entry_metadata.get("trade_mode") != "SWING"
