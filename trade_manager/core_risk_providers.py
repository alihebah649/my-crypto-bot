"""Adapters from canonical core state into the Part-6 risk contracts.

No market or account values are invented here.  The adapters only translate
objects already owned by core into the exact fields required by Part 6.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from .part6_risk import MarketContext, PortfolioSnapshot, SymbolExposure


@dataclass(slots=True)
class CorePortfolioRiskProvider:
    """Translate ``core.models.PortfolioSnapshot`` to Part-6 ``PortfolioSnapshot``."""

    portfolio_engine: Any
    daily_pnl_provider: Callable[[], float] = lambda: 0.0
    weekly_pnl_provider: Callable[[], float] = lambda: 0.0
    monthly_pnl_provider: Callable[[], float] = lambda: 0.0

    def snapshot(self) -> PortfolioSnapshot:
        source = getattr(self.portfolio_engine, "snapshot", None)
        if source is None:
            raise RuntimeError("Portfolio engine has no snapshot")

        return PortfolioSnapshot(
            account_balance=float(getattr(source, "balance")),
            account_equity=float(getattr(source, "equity")),
            used_margin=float(getattr(source, "invested", 0.0)),
            free_margin=float(getattr(source, "free_balance")),
            floating_pnl=float(getattr(source, "unrealized_profit", 0.0)),
            daily_pnl=float(self.daily_pnl_provider()),
            weekly_pnl=float(self.weekly_pnl_provider()),
            monthly_pnl=float(self.monthly_pnl_provider()),
            open_positions=int(getattr(source, "open_positions", 0)),
        )


@dataclass(slots=True)
class CallableMarketContextProvider:
    """Explicit boundary for the application's existing market-data owner."""

    loader: Callable[[str], MarketContext]

    def get_context(self, symbol: str) -> MarketContext:
        context = self.loader(symbol)
        if not isinstance(context, MarketContext):
            raise TypeError("market loader must return Part-6 MarketContext")
        return context


@dataclass(slots=True)
class CallableSymbolExposureProvider:
    """Optional exposure boundary; no duplicate exposure state is maintained."""

    loader: Callable[[str], Optional[SymbolExposure]]

    def get_exposure(self, symbol: str) -> Optional[SymbolExposure]:
        return self.loader(symbol)


@dataclass(slots=True)
class CallableCorrelationProvider:
    """Explicit boundary for the existing correlation-risk calculation owner."""

    loader: Callable[[str], float]

    def get_score(self, symbol: str) -> float:
        value = self.loader(symbol)
        try:
            score = float(value)
        except (TypeError, ValueError):
            return 0.0
        if not (-1.0 <= score <= 1.0):
            raise ValueError("correlation score must be within [-1, 1]")
        return score


@dataclass(slots=True)
class KlineCorrelationProvider:
    """Calculate correlation against currently active, distinct symbols."""

    repository: Any
    candle_loader: Callable[[str], Any]
    lookback_candles: int = 200
    minimum_observations: int = 30

    def get_score(self, symbol: str) -> float:
        import pandas as pd

        target = str(symbol).upper()
        active_symbols = {
            str(position.symbol).upper()
            for position in self.repository.get_open_positions()
            if getattr(position, "status", None) in {
                "OPEN", "HOLD", "REVIEW_REQUIRED", "PARTIALLY_CLOSED"
            } or getattr(getattr(position, "status", None), "name", None) in {
                "OPEN", "HOLD", "REVIEW_REQUIRED", "PARTIALLY_CLOSED"
            }
        }
        active_symbols.discard(target)
        if not active_symbols:
            return 0.0

        target_series = self._close_series(target)
        if target_series is None:
            return 0.0

        best_score = 0.0
        for other in sorted(active_symbols):
            other_series = self._close_series(other)
            if other_series is None:
                continue
            aligned = pd.concat(
                [target_series.rename("target"), other_series.rename("other")],
                axis=1,
                join="inner",
            ).dropna()
            if len(aligned) < self.minimum_observations:
                continue
            returns = aligned.pct_change().dropna().tail(self.lookback_candles)
            if len(returns) < max(2, self.minimum_observations - 1):
                continue
            correlation = returns["target"].corr(returns["other"])
            if pd.isna(correlation):
                continue
            value = float(correlation)
            if abs(value) > abs(best_score):
                best_score = value
        return best_score

    def _close_series(self, symbol: str):
        import pandas as pd

        try:
            rows = list(self.candle_loader(str(symbol).upper()) or [])
        except Exception:
            return None
        points = {}
        for row in rows:
            try:
                open_time = int(row.get("open_time"))
                close = float(row.get("close"))
            except (AttributeError, TypeError, ValueError):
                continue
            if open_time <= 0 or close <= 0:
                continue
            points[open_time] = close
        if len(points) < self.minimum_observations:
            return None
        index = sorted(points)
        return pd.Series([points[key] for key in index], index=index, dtype="float64")


__all__ = [
    "CorePortfolioRiskProvider",
    "CallableMarketContextProvider",
    "CallableSymbolExposureProvider",
    "CallableCorrelationProvider",
    "KlineCorrelationProvider",
]
