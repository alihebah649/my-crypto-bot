from trade_manager.part6_risk import (
    MarketContext,
    PortfolioSnapshot,
    RiskConfig,
    RiskController,
    RiskDecision,
    RiskRejectReason,
    SymbolExposure,
)


def _portfolio(*, used_margin: float, scalp: int = 0, swing: int = 0) -> PortfolioSnapshot:
    equity = 1000.0
    return PortfolioSnapshot(
        account_balance=equity,
        account_equity=equity,
        used_margin=used_margin,
        free_margin=equity - used_margin,
        floating_pnl=0.0,
        daily_pnl=0.0,
        weekly_pnl=0.0,
        monthly_pnl=0.0,
        open_positions=scalp + swing,
        scalp_open_positions=scalp,
        swing_open_positions=swing,
    )


def _market() -> MarketContext:
    return MarketContext(
        symbol="BTCUSDT",
        last_price=100.0,
        bid=100.0,
        ask=100.0,
        spread_percent=0.0,
        atr=1.0,
        volume=1_000_000.0,
        volatility=0.0,
        timestamp=1.0,
    )


def test_scalp_lane_reaches_capacity_before_aggregate_capacity():
    controller = RiskController(RiskConfig())
    result = controller.evaluate(
        account=_portfolio(used_margin=700.0, scalp=15),
        symbol="BTCUSDT",
        signal="SCALP",
        market=_market(),
        symbol_exposure=SymbolExposure("BTCUSDT", 0.0, 0, 0.0, 0.0, ()),
    )
    assert result.decision is RiskDecision.REJECTED
    assert result.reject_reason is RiskRejectReason.MAX_OPEN_SCALP_POSITIONS


def test_swing_lane_reaches_capacity_before_aggregate_capacity():
    controller = RiskController(RiskConfig())
    result = controller.evaluate(
        account=_portfolio(used_margin=700.0, swing=10),
        symbol="BTCUSDT",
        signal="SWING",
        market=_market(),
        symbol_exposure=SymbolExposure("BTCUSDT", 0.0, 0, 0.0, 0.0, ()),
    )
    assert result.decision is RiskDecision.REJECTED
    assert result.reject_reason is RiskRejectReason.MAX_OPEN_SWING_POSITIONS


def test_portfolio_capacity_boundary_is_80_percent_not_25_positions():
    controller = RiskController(RiskConfig())
    below_limit = controller.evaluate(
        account=_portfolio(used_margin=790.0),
        symbol="BTCUSDT",
        signal="SCALP",
        market=_market(),
        symbol_exposure=SymbolExposure("BTCUSDT", 0.0, 0, 0.0, 0.0, ()),
    )
    at_limit = controller.evaluate(
        account=_portfolio(used_margin=800.0),
        symbol="BTCUSDT",
        signal="SCALP",
        market=_market(),
        symbol_exposure=SymbolExposure("BTCUSDT", 0.0, 0, 0.0, 0.0, ()),
    )
    assert below_limit.decision is RiskDecision.APPROVED
    assert at_limit.decision is RiskDecision.REJECTED
    assert at_limit.reject_reason is RiskRejectReason.MAX_PORTFOLIO_EXPOSURE
