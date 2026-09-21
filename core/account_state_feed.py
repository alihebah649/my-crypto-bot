"""Event-driven account-state boundary for multi-account execution.

Market data remains shared across all users. Account state is different: each
connected exchange account has its own balances, orders, and fills. This module
defines an event boundary so those updates can arrive as a stream, while the
existing reconciliation layer remains the periodic safety net.

No exchange/network implementation lives here.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping, Protocol

from core.account_connection import AccountConnection


class AccountEventKind(str, Enum):
    BALANCE_UPDATE = "BALANCE_UPDATE"
    ORDER_UPDATE = "ORDER_UPDATE"
    POSITION_UPDATE = "POSITION_UPDATE"
    CONNECTION_UPDATE = "CONNECTION_UPDATE"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"


@dataclass(frozen=True, slots=True)
class AccountStateEvent:
    """One account-scoped state event.

    Payload is exchange-specific state only. Credential material must never be
    placed in the payload.
    """

    event_id: str
    connection_id: str
    kind: AccountEventKind
    observed_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.event_id).strip():
            raise ValueError("event_id must not be empty")
        if not str(self.connection_id).strip():
            raise ValueError("connection_id must not be empty")


class AccountStateConsumer(Protocol):
    """Consumer for normalized account-state events."""

    def on_event(self, event: AccountStateEvent) -> None:
        ...


class AccountStateFeed(ABC):
    """Transport-neutral account event feed boundary."""

    @abstractmethod
    def subscribe(
        self,
        connection: AccountConnection,
        consumer: AccountStateConsumer,
    ) -> None:
        """Begin receiving state events for one connection."""

    @abstractmethod
    def unsubscribe(self, connection: AccountConnection) -> None:
        """Stop receiving state events for one connection."""

    @abstractmethod
    def is_subscribed(self, connection_id: str) -> bool:
        ...


class UnconfiguredAccountStateFeed(AccountStateFeed):
    """Fail-closed placeholder until a real exchange feed is configured."""

    def subscribe(
        self,
        connection: AccountConnection,
        consumer: AccountStateConsumer,
    ) -> None:
        raise RuntimeError(
            f"No account state feed configured for {connection.profile.exchange.upper()}"
        )

    def unsubscribe(self, connection: AccountConnection) -> None:
        raise RuntimeError(
            f"No account state feed configured for {connection.profile.exchange.upper()}"
        )

    def is_subscribed(self, connection_id: str) -> bool:
        return False


__all__ = [
    "AccountEventKind",
    "AccountStateConsumer",
    "AccountStateEvent",
    "AccountStateFeed",
    "UnconfiguredAccountStateFeed",
]
