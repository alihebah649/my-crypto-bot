"""Part 6 -> Part 8 entry approval adapter.

This is the explicit bridge used by ``PositionManagementFacade``. It keeps
risk evaluation before execution and does not know how orders are submitted.
"""
from __future__ import annotations
from typing import Any, Callable
from .part6_risk import FinalRiskValidator, MarketContext, PortfolioSnapshot


class Part6EntryApprovalAdapter:
    def __init__(self, validator: FinalRiskValidator,
                 portfolio_provider: Callable[[], PortfolioSnapshot],
                 market_provider: Callable[[str], MarketContext],
                 signal_provider: Callable[[str], Any] | None = None) -> None:
        self.validator = validator
        self.portfolio_provider = portfolio_provider
        self.market_provider = market_provider
        self.signal_provider = signal_provider or (lambda symbol: None)

    def approve_open(self, *, symbol: str, quantity: float, entry_price: float,
                     stop_loss: float, take_profit: float | None = None) -> bool:
        if quantity <= 0 or entry_price <= 0 or stop_loss <= 0:
            return False
        account = self.portfolio_provider()
        market = self.market_provider(symbol)
        signal = self.signal_provider(symbol)
        # FinalRiskValidator calculates the authoritative size from account risk.
        # A caller cannot bypass that size by requesting a larger quantity.
        result = self.validator.validate(
            symbol=symbol,
            account=account,
            entry_price=entry_price,
            signal=signal,
            market=market,
        )
        return result.approved and quantity <= result.position_size


__all__ = ["Part6EntryApprovalAdapter"]
