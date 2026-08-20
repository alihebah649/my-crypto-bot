"""Regression coverage for the unified Paper Trading open-position limit."""

from trade_manager.part6_risk import MarketContext, PortfolioSnapshot, RiskConfig, RiskController, RiskDecision


def market():
    return MarketContext(
        symbol="BTCUSDT",
        last_price=100.0,
        bid=99.99,
        ask=100.01,
        spread_percent=0.02,
        atr=2.0,
        volume=1_000_000.0,
        volatility=0.02,
        timestamp=1.0,
    )


def account(open_positions: int):
    return PortfolioSnapshot(
        account_balance=1000.0,
        account_equity=1000.0,
        used_margin=open_positions * 50.0,
        free_margin=1000.0 - open_positions * 50.0,
        floating_pnl=0.0,
        daily_pnl=0.0,
        weekly_pnl=0.0,
        monthly_pnl=0.0,
        open_positions=open_positions,
    )


def test_part6_allows_ninth_position_with_ten_position_limit():
    config = RiskConfig()
    assert config.exposure.max_open_positions == 10

    decision = RiskController(config=config).evaluate(
        account=account(9),
        symbol="BTCUSDT",
        signal=None,
        market=market(),
    )

    assert decision.decision is RiskDecision.APPROVED


def test_part6_rejects_tenth_position_and_above():
    config = RiskConfig()
    decision = RiskController(config=config).evaluate(
        account=account(10),
        symbol="BTCUSDT",
        signal=None,
        market=market(),
    )

    assert decision.decision is RiskDecision.REJECTED
    assert decision.reject_reason.name == "MAX_OPEN_POSITIONS"
