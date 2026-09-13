"""Gateway-level regression coverage for lane and portfolio exposure limits."""

from dataclasses import dataclass

from trade_manager.core_risk_gateway import CoreRiskGateway
from trade_manager.integration_contracts import RiskSizingRequest
from trade_manager.part6_risk import (
    MarketContext,
    PortfolioSnapshot,
    PositionSizeCalculator,
    RiskConfig,
    RiskController,
)


@dataclass
class _PortfolioProvider:
    snapshot_value: PortfolioSnapshot

    def snapshot(self):
        return self.snapshot_value


@dataclass
class _MarketProvider:
    context: MarketContext

    def get_context(self, symbol: str):
        return self.context


def _market():
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


def _account(*, used_margin: float, open_positions: int = 0, scalp: int = 0, swing: int = 0):
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
        open_positions=open_positions,
        scalp_open_positions=scalp,
        swing_open_positions=swing,
    )


def _gateway(account: PortfolioSnapshot) -> CoreRiskGateway:
    config = RiskConfig()
    return CoreRiskGateway(
        controller=RiskController(config=config),
        position_sizer=PositionSizeCalculator(config),
        portfolio_provider=_PortfolioProvider(account),
        market_provider=_MarketProvider(_market()),
    )


def _request(mode: str = "SCALP") -> RiskSizingRequest:
    return RiskSizingRequest(
        symbol="BTCUSDT",
        entry_price=100.0,
        stop_loss=98.0,
        account_equity=1000.0,
        free_balance=1000.0,
        leverage=1.0,
        trade_mode=mode,
    )


def test_core_risk_gateway_enforces_scalp_lane_limit():
    approval = _gateway(_account(used_margin=0.0, scalp=15)).approve(_request("SCALP"))

    assert approval.approved is False
    assert approval.reason == "MAX_OPEN_SCALP_POSITIONS"


def test_core_risk_gateway_enforces_prospective_portfolio_exposure_limit():
    approval = _gateway(_account(used_margin=790.0)).approve(_request("SCALP"))

    assert approval.approved is False
    assert approval.reason == "MAX_PORTFOLIO_EXPOSURE"
    assert approval.metadata["current_exposure"] == 790.0
    assert approval.metadata["position_value"] == 50.0
    assert approval.metadata["prospective_exposure"] == 840.0
    assert approval.metadata["max_exposure"] == 800.0
