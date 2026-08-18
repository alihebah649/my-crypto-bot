"""Application-level composition for the modular Trade Manager."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Protocol
from trade_manager.facade import PositionManagementFacade
from trade_manager.integration_contracts import RiskSizingApproval, RiskSizingRequest
from trade_manager.models import Position

@dataclass(frozen=True, slots=True)
class EntrySignal:
    symbol: str
    entry_price: float
    stop_loss: float
    take_profit: Optional[float] = None
    signal_strength: float = 0.0
    metadata: Mapping[str, Any] = field(default_factory=dict)

class EntryRiskGateway(Protocol):
    def approve(self, request: RiskSizingRequest) -> RiskSizingApproval: ...

class EntryRiskProvider(Protocol):
    def account_equity(self) -> float: ...
    def free_balance(self) -> float: ...
    def estimated_fee(self, *, symbol: str, quantity: float, price: float) -> float: ...

class TradeManagerApplicationCoordinator:
    """Single application entry point: signal -> risk -> facade -> execution."""
    def __init__(self, *, facade: PositionManagementFacade, risk_gateway: EntryRiskGateway,
                 account_provider: EntryRiskProvider) -> None:
        self.facade = facade
        self.risk_gateway = risk_gateway
        self.account_provider = account_provider

    def open_from_signal(self, signal: EntrySignal) -> Optional[Position]:
        if not signal.symbol or signal.entry_price <= 0 or signal.stop_loss <= 0 or signal.stop_loss == signal.entry_price:
            return None
        equity = float(self.account_provider.account_equity())
        free_balance = float(self.account_provider.free_balance())
        if equity <= 0 or free_balance <= 0:
            return None
        preliminary = RiskSizingRequest(
            symbol=signal.symbol, entry_price=signal.entry_price, stop_loss=signal.stop_loss,
            account_equity=equity, free_balance=free_balance, leverage=1.0,
        )
        approval = self.risk_gateway.approve(preliminary)
        if not approval.approved or approval.quantity <= 0:
            return None
        position = self.facade.open_position(
            symbol=signal.symbol, quantity=approval.quantity,
            entry_price=signal.entry_price, stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            entry_metadata={"signal_strength": signal.signal_strength, **dict(signal.metadata),
                            "composition": "TradeManagerApplicationCoordinator", "risk_reason": approval.reason},
            account_equity=equity, free_balance=free_balance,
            estimated_fee=self.account_provider.estimated_fee(
                symbol=signal.symbol, quantity=approval.quantity, price=signal.entry_price),
        )
        return position

__all__ = ["EntrySignal", "EntryRiskGateway", "EntryRiskProvider", "TradeManagerApplicationCoordinator"]
