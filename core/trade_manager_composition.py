"""Application-level composition for the modular Trade Manager.

This module is deliberately small: it does not implement strategy, risk math,
or broker execution. It defines the explicit hand-off from an application
signal to the Part-6 risk gateway and then to the Part-8 facade.

The legacy runtime must not call the facade directly without passing through
this boundary. Providers are injected so existing core implementations remain
the owners of account and market data.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Protocol

from trade_manager.facade import PositionManagementFacade
from trade_manager.integration_contracts import (
    RiskSizingApproval,
    RiskSizingRequest,
    RiskGateway,
)
from trade_manager.models import Position


@dataclass(frozen=True, slots=True)
class EntrySignal:
    """Normalized application signal consumed by the composition layer."""

    symbol: str
    entry_price: float
    stop_loss: float
    take_profit: Optional[float] = None
    signal_strength: float = 0.0
    metadata: Mapping[str, Any] = field(default_factory=dict)


class EntryRiskGateway(Protocol):
    """Part-6-compatible risk boundary used by the application layer."""

    def approve(self, request: RiskSizingRequest) -> RiskSizingApproval:
        ...


class EntryRiskProvider(Protocol):
    """Supplies the account inputs required by Part 6."""

    def account_equity(self) -> float:
        ...

    def free_balance(self) -> float:
        ...

    def estimated_fee(self, *, symbol: str, quantity: float, price: float) -> float:
        ...


class TradeManagerApplicationCoordinator:
    """Single application entry point for opening a Trade Manager position.

    Flow is intentionally fixed:

        signal -> Part-6 approval -> Part-8 facade -> execution -> position

    No order is submitted here and no Position object is constructed here.
    The facade remains the sole owner of Position creation after execution.
    """

    def __init__(
        self,
        *,
        facade: PositionManagementFacade,
        risk_gateway: EntryRiskGateway,
        account_provider: EntryRiskProvider,
    ) -> None:
        self.facade = facade
        self.risk_gateway = risk_gateway
        self.account_provider = account_provider

    def open_from_signal(self, signal: EntrySignal) -> Optional[Position]:
        if not signal.symbol or signal.entry_price <= 0 or signal.stop_loss <= 0:
            return None
        if signal.stop_loss == signal.entry_price:
            return None

        equity = float(self.account_provider.account_equity())
        free_balance = float(self.account_provider.free_balance())
        if equity <= 0 or free_balance <= 0:
            return None

        # First ask Part 6 for the authoritative risk decision and size.
        # The facade will perform its own mandatory approval callback as a
        # second gate immediately before the actual BUY execution.
        preliminary = RiskSizingRequest(
            symbol=signal.symbol,
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            account_equity=equity,
            free_balance=free_balance,
            leverage=1.0,
        )
        approval = self.risk_gateway.approve(preliminary)
        if not approval.approved or approval.quantity <= 0:
            return None

        position = self.facade.open_position(
            symbol=signal.symbol,
            quantity=approval.quantity,
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            entry_metadata={
                "signal_strength": signal.signal_strength,
                **dict(signal.metadata),
                "composition": "TradeManagerApplicationCoordinator",
                "risk_reason": approval.reason,
            },
        )
        return position


__all__ = [
    "EntrySignal",
    "EntryRiskGateway",
    "EntryRiskProvider",
    "TradeManagerApplicationCoordinator",
]
