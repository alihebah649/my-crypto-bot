"""Final application-level Paper Trading lifecycle contracts.

These tests deliberately use ShadowTradeManagerRuntime so the path is:
strategy/runtime market state -> Part 6 -> Trade Manager -> Core/Part 7 paper
execution -> Part 8 lifecycle -> Smart Hold/Recovery -> explicit exit -> P&L.

They do not use the legacy boolean risk_approval compatibility path.
"""

from __future__ import annotations

import time

import pytest

from trade_manager.integration_contracts import RiskSizingRequest
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


def test_full_paper_buy_and_successful_manual_close_path():
    runtime = build_runtime()

    position = runtime.open_position("BTCUSDT", 100.0, 96.0)
    assert position is not None
    assert position.status is PositionStatus.OPEN
    assert position.entry_fee == pytest.approx(0.5)
    assert runtime.execution_adapter.balance.assets["BTCUSDT"] == pytest.approx(position.quantity)

    runtime.update_market("BTCUSDT", price=110.0, **MARKET)
    closed = runtime.facade.close_position(position.position_id, 110.0)

    assert closed is not None
    assert closed.status is PositionStatus.CLOSED
    assert closed.exit_fee == pytest.approx(closed.quantity * 110.0 * 0.001)
    assert closed.realized_pnl > 0.0
    assert runtime.execution_adapter.balance.assets.get("BTCUSDT", 0.0) == pytest.approx(0.0)


def test_part6_rejection_happens_before_any_paper_buy():
    runtime = build_runtime()
    runtime.loss_tracker.update(daily_pnl=-60.0)

    approval = runtime.risk_gateway.approve(
        RiskSizingRequest(
            symbol="ETHUSDT",
            entry_price=100.0,
            stop_loss=98.0,
            account_equity=1000.0,
            free_balance=1000.0,
            leverage=1.0,
        )
    )

    assert approval.approved is False
    assert approval.reason == "DAILY_LOSS_LIMIT"
    assert runtime.execution_adapter.balance.cash == pytest.approx(1000.0)
    assert runtime.repository.get_open_positions() == []


def test_losing_position_is_held_then_review_required_without_auto_sell():
    runtime = build_runtime()
    position = runtime.open_position("BTCUSDT", 100.0, 96.0)
    assert position is not None

    runtime.update_market("BTCUSDT", price=99.0, **MARKET)
    runtime.evaluate_position("BTCUSDT")
    held = runtime.repository.get(position.position_id)
    assert held is not None
    assert held.status is PositionStatus.HOLD
    assert runtime.execution_adapter.balance.assets["BTCUSDT"] == pytest.approx(position.quantity)

    held.entered_hold_at = time.time() - (8 * 86400)
    runtime.evaluate_position("BTCUSDT")
    review = runtime.repository.get(position.position_id)
    assert review is not None
    assert review.status is PositionStatus.REVIEW_REQUIRED
    assert runtime.execution_adapter.balance.assets["BTCUSDT"] == pytest.approx(position.quantity)

    # REVIEW_REQUIRED is informational. Only an explicit close request may sell.
    closed = runtime.facade.close_position(position.position_id, 99.0)
    assert closed is not None
    assert closed.status is PositionStatus.CLOSED


def test_failed_sell_preserves_owned_position_and_does_not_record_closed_pnl():
    runtime = build_runtime()
    position = runtime.open_position("BTCUSDT", 100.0, 96.0)
    assert position is not None

    runtime.execution_adapter.balance.assets["BTCUSDT"] = 0.0
    runtime.update_market("BTCUSDT", price=90.0, ema100=95.0, **{k: v for k, v in MARKET.items() if k != "ema100"})
    runtime.evaluate_position("BTCUSDT")

    stored = runtime.repository.get(position.position_id)
    assert stored is not None
    assert stored.status is not PositionStatus.CLOSED
    assert runtime.loss_tracker.snapshot().daily_pnl == pytest.approx(0.0)


def test_realized_loss_feeds_part6_and_locks_next_entry():
    runtime = build_runtime()
    position = runtime.open_position("BTCUSDT", 100.0, 96.0)
    assert position is not None

    runtime.update_market("BTCUSDT", price=70.0, **MARKET)
    closed = runtime.facade.close_position(position.position_id, 70.0)
    assert closed is not None
    assert closed.realized_pnl < 0.0

    # Synchronization feeds the realized net result into Part 6 exactly once.
    runtime.update_market("BTCUSDT", price=70.0, **MARKET)
    loss = runtime.loss_tracker.snapshot()
    assert loss.daily_pnl == pytest.approx(closed.realized_pnl)
    assert loss.weekly_pnl == pytest.approx(closed.realized_pnl)
    assert loss.monthly_pnl == pytest.approx(closed.realized_pnl)

    approval = runtime.risk_gateway.approve(
        RiskSizingRequest(
            symbol="ETHUSDT",
            entry_price=100.0,
            stop_loss=98.0,
            account_equity=1000.0,
            free_balance=1000.0,
            leverage=1.0,
        )
    )
    assert approval.approved is False
    assert approval.reason == "DAILY_LOSS_LIMIT"
    assert runtime.risk_controller.lock_manager.is_locked() is True


def test_spot_contract_rejects_leverage_above_one():
    runtime = build_runtime()
    approval = runtime.risk_gateway.approve(
        RiskSizingRequest(
            symbol="BTCUSDT",
            entry_price=100.0,
            stop_loss=98.0,
            account_equity=1000.0,
            free_balance=1000.0,
            leverage=2.0,
        )
    )
    assert approval.approved is False
    assert approval.reason == "LEVERAGE_NOT_ALLOWED_SPOT"
