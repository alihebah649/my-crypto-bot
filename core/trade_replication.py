"""Shared trade-intent replication primitives for multi-account execution.

The trading engine produces one market decision. This module converts that
decision into account-specific execution plans without fetching market data,
re-evaluating indicators, or executing exchange orders.

Per-account balance/position state remains an execution-time concern.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any
from uuid import uuid4

from core.execution_models import OrderSide


class ReplicationAction(str, Enum):
    OPEN = "OPEN"
    CLOSE = "CLOSE"


@dataclass(frozen=True, slots=True)
class MasterTradeIntent:
    """Canonical trade instruction emitted once by the trading engine."""

    intent_id: str
    symbol: str
    side: OrderSide
    action: ReplicationAction
    reference_capital: float
    target_position_value: float = 0.0
    close_fraction: float = 1.0
    trade_mode: str = ""
    stop_loss_price: float | None = None
    strategy_snapshot_id: str = ""
    metadata: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if not str(self.intent_id).strip():
            raise ValueError("intent_id must not be empty")
        if not str(self.symbol).strip():
            raise ValueError("symbol must not be empty")
        if self.reference_capital <= 0.0:
            raise ValueError("reference_capital must be positive")
        if self.action is ReplicationAction.OPEN and self.target_position_value <= 0.0:
            raise ValueError("OPEN intent requires a positive target_position_value")
        if self.action is ReplicationAction.CLOSE and not 0.0 < self.close_fraction <= 1.0:
            raise ValueError("CLOSE intent close_fraction must be in (0, 1]")

    @property
    def target_allocation_percent(self) -> float:
        """Fraction of reference capital allocated by the master order."""
        return self.target_position_value / self.reference_capital

    @classmethod
    def open(
        cls,
        *,
        symbol: str,
        side: OrderSide,
        reference_capital: float,
        target_position_value: float,
        trade_mode: str = "",
        stop_loss_price: float | None = None,
        strategy_snapshot_id: str = "",
        metadata: dict[str, Any] | None = None,
        intent_id: str | None = None,
    ) -> "MasterTradeIntent":
        return cls(
            intent_id=intent_id or f"INTENT-{uuid4().hex[:16]}",
            symbol=symbol.upper(),
            side=side,
            action=ReplicationAction.OPEN,
            reference_capital=reference_capital,
            target_position_value=target_position_value,
            trade_mode=str(trade_mode or "").upper(),
            stop_loss_price=stop_loss_price,
            strategy_snapshot_id=str(strategy_snapshot_id or ""),
            metadata=dict(metadata or {}),
        )

    @classmethod
    def close(
        cls,
        *,
        symbol: str,
        side: OrderSide = OrderSide.SELL,
        reference_capital: float = 1.0,
        close_fraction: float = 1.0,
        trade_mode: str = "",
        strategy_snapshot_id: str = "",
        metadata: dict[str, Any] | None = None,
        intent_id: str | None = None,
    ) -> "MasterTradeIntent":
        return cls(
            intent_id=intent_id or f"INTENT-{uuid4().hex[:16]}",
            symbol=symbol.upper(),
            side=side,
            action=ReplicationAction.CLOSE,
            reference_capital=reference_capital,
            close_fraction=close_fraction,
            trade_mode=str(trade_mode or "").upper(),
            strategy_snapshot_id=str(strategy_snapshot_id or ""),
            metadata=dict(metadata or {}),
        )


@dataclass(frozen=True, slots=True)
class FollowerAccount:
    """Minimal follower state needed before an execution plan is built."""

    connection_id: str
    capital_basis: float
    enabled: bool = True

    def __post_init__(self) -> None:
        if not str(self.connection_id).strip():
            raise ValueError("connection_id must not be empty")
        if self.capital_basis <= 0.0:
            raise ValueError("capital_basis must be positive")


@dataclass(frozen=True, slots=True)
class ReplicaInstruction:
    """Account-specific plan derived from one shared MasterTradeIntent."""

    intent_id: str
    connection_id: str
    symbol: str
    side: OrderSide
    action: ReplicationAction
    target_quote_value: float = 0.0
    close_fraction: float = 0.0
    trade_mode: str = ""
    strategy_snapshot_id: str = ""
    metadata: dict[str, Any] | None = None


class TradeReplicationPlanner:
    """Pure fan-out planner; it does not access market data or execute orders."""

    MARKET_DATA_SCOPE = "SHARED"

    @classmethod
    def plan(
        cls,
        intent: MasterTradeIntent,
        followers: list[FollowerAccount] | tuple[FollowerAccount, ...],
    ) -> list[ReplicaInstruction]:
        instructions: list[ReplicaInstruction] = []

        for follower in followers:
            if not follower.enabled:
                continue

            metadata = {
                "market_data_scope": cls.MARKET_DATA_SCOPE,
                "source_intent_id": intent.intent_id,
                **dict(intent.metadata or {}),
            }

            if intent.action is ReplicationAction.OPEN:
                target_quote_value = (
                    follower.capital_basis * intent.target_allocation_percent
                )
                instructions.append(
                    ReplicaInstruction(
                        intent_id=intent.intent_id,
                        connection_id=follower.connection_id,
                        symbol=intent.symbol,
                        side=intent.side,
                        action=ReplicationAction.OPEN,
                        target_quote_value=target_quote_value,
                        trade_mode=intent.trade_mode,
                        strategy_snapshot_id=intent.strategy_snapshot_id,
                        metadata=metadata,
                    )
                )
            else:
                instructions.append(
                    ReplicaInstruction(
                        intent_id=intent.intent_id,
                        connection_id=follower.connection_id,
                        symbol=intent.symbol,
                        side=intent.side,
                        action=ReplicationAction.CLOSE,
                        close_fraction=intent.close_fraction,
                        trade_mode=intent.trade_mode,
                        strategy_snapshot_id=intent.strategy_snapshot_id,
                        metadata=metadata,
                    )
                )

        return instructions


__all__ = [
    "FollowerAccount",
    "MasterTradeIntent",
    "ReplicaInstruction",
    "ReplicationAction",
    "TradeReplicationPlanner",
]
