"""Verify the Shadow application feeds realized P&L back into Part 6."""

from trade_manager.integration_contracts import RiskSizingRequest
from trade_manager.shadow_integration import ShadowTradeManagerRuntime


def test_closed_loss_updates_daily_weekly_monthly_risk_snapshot():
    runtime = ShadowTradeManagerRuntime(initial_cash=1000.0, fee_rate=0.001)
    runtime.update_market(
        "BTCUSDT", price=100.0, bid=99.99, ask=100.01,
        spread_percent=0.02, atr=2.0, volume_usdt=1_000_000.0, ema100=90.0,
    )

    position = runtime.open_position("BTCUSDT", 100.0, 96.0)
    assert position is not None

    runtime.update_market(
        "BTCUSDT", price=70.0, bid=69.99, ask=70.01,
        spread_percent=0.02, atr=2.0, volume_usdt=1_000_000.0, ema100=95.0,
    )
    closed = runtime.facade.close_position(position.position_id, 70.0)
    assert closed is not None
    assert closed.realized_pnl < -50.0

    # The runtime's next market synchronization feeds the closed result into
    # the Part-6 daily/weekly/monthly loss snapshot.
    runtime.update_market(
        "BTCUSDT", price=70.0, bid=69.99, ask=70.01,
        spread_percent=0.02, atr=2.0, volume_usdt=1_000_000.0, ema100=95.0,
    )

    loss = runtime.loss_tracker.snapshot()
    assert loss.daily_pnl == closed.realized_pnl
    assert loss.weekly_pnl == closed.realized_pnl
    assert loss.monthly_pnl == closed.realized_pnl

    approval = runtime.risk_gateway.approve(
        RiskSizingRequest(
            symbol="ETHUSDT", entry_price=100.0, stop_loss=98.0,
            account_equity=1000.0, free_balance=1000.0, leverage=1.0,
        )
    )
    assert approval.approved is False
    assert approval.reason == "DAILY_LOSS_LIMIT"
