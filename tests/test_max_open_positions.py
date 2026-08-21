"""Regression coverage for independent Paper Trading open-position limits."""

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


def account(open_positions: int, scalp: int = 0, swing: int = 0):
    return PortfolioSnapshot(
        account_balance=2000.0,
        account_equity=2000.0,
        used_margin=open_positions * 50.0,
        free_margin=2000.0 - open_positions * 50.0,
        floating_pnl=0.0,
        daily_pnl=0.0,
        weekly_pnl=0.0,
        monthly_pnl=0.0,
        open_positions=open_positions,
        scalp_open_positions=scalp,
        swing_open_positions=swing,
    )


def test_part6_uses_15_scalp_and_10_swing_limits_independently():
    config = RiskConfig()
    assert config.exposure.max_scalp_positions == 15
    assert config.exposure.max_swing_positions == 10
    assert config.exposure.max_open_positions == 25

    controller = RiskController(config=config)

    assert controller.evaluate(account=account(14, scalp=14, swing=0), symbol="BTCUSDT", signal="SCALP", market=market()).decision is RiskDecision.APPROVED
    scalp_rejected = controller.evaluate(account=account(15, scalp=15, swing=0), symbol="BTCUSDT", signal="SCALP", market=market())
    assert scalp_rejected.decision is RiskDecision.REJECTED
    assert scalp_rejected.reject_reason.name == "MAX_OPEN_SCALP_POSITIONS"

    assert controller.evaluate(account=account(10, scalp=10, swing=0), symbol="BTCUSDT", signal="SWING", market=market()).decision is RiskDecision.APPROVED
    swing_rejected = controller.evaluate(account=account(10, scalp=0, swing=10), symbol="BTCUSDT", signal="SWING", market=market())
    assert swing_rejected.decision is RiskDecision.REJECTED
    assert swing_rejected.reject_reason.name == "MAX_OPEN_SWING_POSITIONS"


def test_part6_allows_25_combined_positions_when_each_lane_is_below_its_cap():
    config = RiskConfig()
    decision = RiskController(config=config).evaluate(
        account=account(24, scalp=14, swing=10),
        symbol="BTCUSDT",
        signal="SCALP",
        market=market(),
    )
    assert decision.decision is RiskDecision.APPROVED

    total_rejected = RiskController(config=config).evaluate(
        account=account(25, scalp=15, swing=10),
        symbol="BTCUSDT",
        signal="SWING",
        market=market(),
    )
    assert total_rejected.decision is RiskDecision.REJECTED
    assert total_rejected.reject_reason.name == "MAX_OPEN_SWING_POSITIONS"
