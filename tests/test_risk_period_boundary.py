from __future__ import annotations

from trade_manager.part6_risk import MarketContext, PortfolioSnapshot, RiskConfig, RiskController, RiskDecision


def _account(daily_pnl: float) -> PortfolioSnapshot:
    return PortfolioSnapshot(
        account_balance=1000.0, account_equity=1000.0, used_margin=0.0,
        free_margin=1000.0, floating_pnl=0.0, daily_pnl=daily_pnl,
        weekly_pnl=daily_pnl, monthly_pnl=daily_pnl, open_positions=0,
    )


def _market() -> MarketContext:
    return MarketContext(symbol="BTCUSDT", last_price=100.0, bid=99.99, ask=100.01,
                         spread_percent=0.02, atr=2.0, volume=1_000_000.0,
                         volatility=0.02, timestamp=1.0)


def test_sub_limit_realized_loss_does_not_lock():
    config = RiskConfig()
    controller = RiskController(config)
    controller.loss_tracker.update(daily_pnl=-10.0, weekly_pnl=-10.0, monthly_pnl=-10.0)
    result = controller.evaluate(account=_account(-10.0), symbol="BTCUSDT", signal="SWING", market=_market())
    assert result.decision is RiskDecision.APPROVED
    assert controller.lock_manager.is_locked() is False


def test_daily_limit_breach_locks():
    config = RiskConfig()
    controller = RiskController(config)
    controller.loss_tracker.update(daily_pnl=-50.0, weekly_pnl=-50.0, monthly_pnl=-50.0)
    result = controller.evaluate(account=_account(-50.0), symbol="BTCUSDT", signal="SWING", market=_market())
    assert result.decision is RiskDecision.REJECTED
    assert result.reject_reason.name == "DAILY_LOSS_LIMIT"
    assert controller.lock_manager.is_locked() is True
