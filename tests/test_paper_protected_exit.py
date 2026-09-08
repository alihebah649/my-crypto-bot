"""Regression tests for protected Paper Trading exits.

The paper stop model must use the configured protected price rather than a
later polling price.  Trailing/profit exits must continue to use their
observed execution price.
"""
from __future__ import annotations

from trade_manager.risk_manager import PositionExitDecision, PositionExitReason
from trade_manager.shadow_integration import ShadowTradeManagerRuntime
from trade_manager.models import PositionStatus

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


def test_stop_loss_exit_uses_configured_stop_price():
    runtime = build_runtime()
    position = runtime.open_position("BTCUSDT", 100.0, 98.0)
    assert position is not None

    # The observed polling price is materially below the configured stop.
    runtime.update_market("BTCUSDT", price=95.0, **MARKET)
    decision = PositionExitDecision(
        True,
        PositionExitReason.STOP_LOSS,
        95.0,
        "regression stop breach",
    )
    closed = runtime.facade.execute_decision(position.position_id, decision)

    assert closed is not None
    assert closed.status is PositionStatus.CLOSED
    assert closed.exit_price == 98.0
    assert closed.exit_metadata["paper_stop_fill"] is True
    assert closed.exit_metadata["paper_stop_price"] == 98.0
    assert closed.exit_metadata["paper_observed_price_at_trigger"] == 95.0


def test_break_even_exit_uses_configured_protected_price():
    runtime = build_runtime()
    position = runtime.open_position("BTCUSDT", 100.0, 98.0)
    assert position is not None

    # Simulate a protected stop moved to the break-even level.
    position.stop_loss = 100.0
    runtime.repository.update(position)
    runtime.update_market("BTCUSDT", price=97.0, **MARKET)
    decision = PositionExitDecision(
        True,
        PositionExitReason.BREAK_EVEN,
        97.0,
        "regression break-even breach",
    )
    closed = runtime.facade.execute_decision(position.position_id, decision)

    assert closed is not None
    assert closed.status is PositionStatus.CLOSED
    assert closed.exit_price == 100.0
    assert closed.exit_metadata["paper_stop_fill"] is True
    assert closed.exit_metadata["paper_stop_price"] == 100.0
    assert closed.exit_metadata["paper_stop_reason"] == "BREAK_EVEN"


def test_non_protected_trailing_exit_keeps_observed_price():
    runtime = build_runtime()
    position = runtime.open_position("BTCUSDT", 100.0, 98.0)
    assert position is not None

    runtime.update_market("BTCUSDT", price=103.0, **MARKET)
    decision = PositionExitDecision(
        True,
        PositionExitReason.TRAILING_STOP,
        103.0,
        "regression trailing exit",
    )
    closed = runtime.facade.execute_decision(position.position_id, decision)

    assert closed is not None
    assert closed.status is PositionStatus.CLOSED
    assert closed.exit_price == 103.0
    assert closed.exit_metadata.get("paper_stop_fill") is not True
