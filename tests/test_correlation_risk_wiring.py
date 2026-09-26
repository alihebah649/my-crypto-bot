from __future__ import annotations

from types import SimpleNamespace

import pytest

from trade_manager.core_risk_gateway import CoreRiskGateway
from trade_manager.correlation_provider import KlineCorrelationProvider
from trade_manager.integration_contracts import RiskSizingRequest
from trade_manager.models import PositionStatus
from trade_manager.part6_risk import (
    MarketContext,
    PortfolioSnapshot,
    RiskConfig,
    RiskController,
    SymbolExposure,
    PositionSizeCalculator,
)


class _Portfolio:
    def snapshot(self):
        return PortfolioSnapshot(
            account_balance=1000.0,
            account_equity=1000.0,
            used_margin=0.0,
            free_margin=1000.0,
            floating_pnl=0.0,
            daily_pnl=0.0,
            weekly_pnl=0.0,
            monthly_pnl=0.0,
            open_positions=0,
        )


class _Market:
    def get_context(self, symbol: str):
        return MarketContext(
            symbol=symbol,
            last_price=100.0,
            bid=100.0,
            ask=100.0,
            spread_percent=0.0,
            atr=1.0,
            volume=1_000_000.0,
            volatility=0.01,
            timestamp=1_000.0,
        )


class _Exposure:
    def get_exposure(self, symbol: str):
        return SymbolExposure(
            symbol=symbol,
            exposure_percent=0.0,
            open_positions=0,
            total_quantity=0.0,
            total_value=0.0,
            open_trade_modes=(),
        )


class _Correlation:
    def __init__(self, score: float):
        self.score = score

    def get_score(self, symbol: str) -> float:
        return self.score


def _gateway(score: float):
    config = RiskConfig()
    return CoreRiskGateway(
        controller=RiskController(config),
        position_sizer=PositionSizeCalculator(config),
        portfolio_provider=_Portfolio(),
        market_provider=_Market(),
        exposure_provider=_Exposure(),
        correlation_provider=_Correlation(score),
    )


def test_correlation_score_reaches_part6_and_rejects_above_configured_limit():
    approval = _gateway(0.85).approve(
        RiskSizingRequest(
            symbol="ETHUSDT",
            entry_price=100.0,
            stop_loss=98.0,
            account_equity=1000.0,
            free_balance=1000.0,
            trade_mode="SCALP",
        )
    )

    assert approval.approved is False
    assert approval.reason == "CORRELATION_LIMIT"
    assert approval.metadata["correlation_score"] == pytest.approx(0.85)


def test_correlation_score_at_limit_does_not_change_existing_boundary():
    approval = _gateway(0.80).approve(
        RiskSizingRequest(
            symbol="ETHUSDT",
            entry_price=100.0,
            stop_loss=98.0,
            account_equity=1000.0,
            free_balance=1000.0,
            trade_mode="SCALP",
        )
    )

    assert approval.approved is True
    assert approval.metadata["correlation_score"] == pytest.approx(0.80)


def _rows(values):
    return [
        {"open_time": index, "close": float(value)}
        for index, value in enumerate(values, start=1)
    ]


def test_kline_correlation_provider_uses_active_other_symbols_and_max_abs_score():
    positions = [
        SimpleNamespace(symbol="BTCUSDT", status=PositionStatus.OPEN),
        SimpleNamespace(symbol="ETHUSDT", status=PositionStatus.OPEN),
        SimpleNamespace(symbol="SOLUSDT", status=PositionStatus.OPEN),
    ]

    class Repository:
        def get_open_positions(self):
            return positions

    values = list(range(1, 61))
    inverse = list(range(60, 0, -1))

    def loader(symbol):
        if symbol == "ETHUSDT":
            return _rows(values)
        if symbol == "SOLUSDT":
            return _rows(inverse)
        if symbol == "BTCUSDT":
            return _rows(values)
        return []

    provider = KlineCorrelationProvider(
        Repository(),
        loader,
        lookback_candles=50,
        minimum_observations=30,
    )

    score = provider.get_score("BTCUSDT")

    assert score == pytest.approx(1.0)


def test_kline_correlation_provider_returns_zero_without_other_symbols_or_data():
    class Repository:
        def __init__(self, positions):
            self.positions = positions

        def get_open_positions(self):
            return self.positions

    provider = KlineCorrelationProvider(
        Repository([SimpleNamespace(symbol="BTCUSDT", status=PositionStatus.OPEN)]),
        lambda symbol: [],
    )
    assert provider.get_score("BTCUSDT") == 0.0
