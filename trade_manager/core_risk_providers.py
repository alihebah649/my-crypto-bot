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


__all__ = [
    "CorePortfolioRiskProvider",
    "CallableMarketContextProvider",
    "CallableSymbolExposureProvider",
]
