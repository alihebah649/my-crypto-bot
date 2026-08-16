"""Integration contracts for Trade Manager Parts 6-8.

Spot-only boundary between risk, execution and position management.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional, Protocol, Sequence


class TradeManagerSide(str, Enum):
    LONG = "LONG"


class ExecutionSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class ExecutionOutcome(str, Enum):
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True, slots=True)
class RiskSizingRequest:
    symbol: str
    entry_price: float
    stop_loss: float
    account_equity: float
    free_balance: float
    estimated_fee: float = 0.0
    maintenance_margin: float = 0.0
    leverage: float = 1.0


@dataclass(frozen=True, slots=True)
class RiskSizingApproval:
    approved: bool
    reason: str
    quantity: float = 0.0
    position_value: float = 0.0
    capital_required: float = 0.0
    risk_amount: float = 0.0
    stop_distance: float = 0.0
    leverage: float = 1.0
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ExecutionRequest:
    symbol: str
    side: ExecutionSide
    quantity: float
    order_type: str = "MARKET"
    price: Optional[float] = None
    stop_price: Optional[float] = None
    client_order_id: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ExecutionOutcomeRecord:
    success: bool
    outcome: ExecutionOutcome
    symbol: str
    side: ExecutionSide
    requested_quantity: float
    executed_quantity: float
    average_price: float
    exchange_order_id: Optional[str] = None
    client_order_id: Optional[str] = None
    commission: float = 0.0
    commission_asset: str = ""
    message: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)


class RiskGateway(Protocol):
    def approve(self, request: RiskSizingRequest) -> RiskSizingApproval:
        ...


class ExecutionGateway(Protocol):
    def submit(self, request: ExecutionRequest) -> ExecutionOutcomeRecord:
        ...

    def cancel(self, *, symbol: str, exchange_order_id: Optional[str] = None,
               client_order_id: Optional[str] = None) -> ExecutionOutcomeRecord:
        ...

    def close_spot(self, *, symbol: str, quantity: float,
                   client_order_id: Optional[str] = None) -> ExecutionOutcomeRecord:
        ...


class PositionRepositoryGateway(Protocol):
    def get_open_positions(self) -> Sequence[Any]:
        ...

    def save(self, position: Any) -> None:
        ...


class MarketGateway(Protocol):
    def get_snapshot(self, symbol: str) -> Any:
        ...


@dataclass(frozen=True, slots=True)
class IntegrationContract:
    version: str = "1.0"
    spot_only: bool = True
    leverage_required: float = 1.0
    risk_before_execution: bool = True
    execution_before_position_commit: bool = True
    review_required_is_not_auto_exit: bool = True
    fee_aware_pnl: bool = True


CONTRACT = IntegrationContract()
