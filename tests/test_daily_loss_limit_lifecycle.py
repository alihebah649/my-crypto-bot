from trade_manager.part6_risk import (
    LossTracker,
    MarketContext,
    PortfolioSnapshot,
    RiskConfig,
    RiskController,
    RiskDecision,
    RiskRejectReason,
)


def _account() -> PortfolioSnapshot:
    return PortfolioSnapshot(
        account_balance=1000.0, account_equity=1000.0, used_margin=0.0,
        free_margin=1000.0, floating_pnl=0.0, daily_pnl=0.0,
        weekly_pnl=0.0, monthly_pnl=0.0, open_positions=0,
    )


def _market() -> MarketContext:
    return MarketContext(
        symbol="BTCUSDT", last_price=100.0, bid=99.9, ask=100.1,
        spread_percent=0.2, atr=1.0, volume=1_000_000.0,
        volatility=0.1, timestamp=0.0,
    )


def test_small_realized_loss_does_not_lock_entries():
    tracker = LossTracker()
    controller = RiskController(RiskConfig(), tracker)
    tracker.update(daily_pnl=-1.50, weekly_pnl=-1.50, monthly_pnl=-1.50)
    result = controller.evaluate(account=_account(), symbol="BTCUSDT", signal="SCALP", market=_market())
    assert result.decision is RiskDecision.APPROVED
    assert controller.lock_manager.is_locked() is False


def test_daily_loss_limit_locks_only_at_configured_threshold():
    tracker = LossTracker()
    controller = RiskController(RiskConfig(), tracker)
    tracker.update(daily_pnl=-49.99, weekly_pnl=-49.99, monthly_pnl=-49.99)
    below_limit = controller.evaluate(account=_account(), symbol="BTCUSDT", signal="SCALP", market=_market())
    assert below_limit.decision is RiskDecision.APPROVED
    assert controller.lock_manager.is_locked() is False

    tracker.update(daily_pnl=-50.00, weekly_pnl=-50.00, monthly_pnl=-50.00)
    at_limit = controller.evaluate(account=_account(), symbol="BTCUSDT", signal="SCALP", market=_market())
    assert at_limit.decision is RiskDecision.REJECTED
    assert at_limit.reject_reason is RiskRejectReason.DAILY_LOSS_LIMIT
    assert controller.lock_manager.is_locked() is True


def test_daily_lock_can_be_explicitly_reset_for_new_period():
    tracker = LossTracker()
    controller = RiskController(RiskConfig(), tracker)
    tracker.update(daily_pnl=-50.00, weekly_pnl=-50.00, monthly_pnl=-50.00)
    blocked = controller.evaluate(account=_account(), symbol="BTCUSDT", signal="SCALP", market=_market())
    assert blocked.reject_reason is RiskRejectReason.DAILY_LOSS_LIMIT

    tracker.update(daily_pnl=0.0, weekly_pnl=0.0, monthly_pnl=0.0)
    still_locked = controller.evaluate(account=_account(), symbol="BTCUSDT", signal="SCALP", market=_market())
    assert still_locked.decision is RiskDecision.REJECTED
    assert still_locked.reject_reason is RiskRejectReason.RISK_LOCKED

    controller.lock_manager.unlock()
    reset = controller.evaluate(account=_account(), symbol="BTCUSDT", signal="SCALP", market=_market())
    assert reset.decision is RiskDecision.APPROVED
