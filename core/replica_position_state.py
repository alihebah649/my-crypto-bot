"""Per-account replica-position state contract.

One master OPEN can create independent follower positions. This module records
the mapping needed later for safe CLOSE replication without re-evaluating
strategy or fetching market data per follower.

It is intentionally a state contract only: it does not execute orders,
calculate risk, or decide when a position should close.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import threading


class ReplicaPositionStatus(str, Enum):
    OPEN = "OPEN"
    PARTIALLY_CLOSED = "PARTIALLY_CLOSED"
    CLOSED = "CLOSED"


@dataclass(frozen=True, slots=True)
class ReplicaPositionRecord:
    """Account-local position created from one shared master intent."""

    position_id: str
    connection_id: str
    source_intent_id: str
    symbol: str
    quantity: float
    remaining_quantity: float
    entry_price: float
    stop_loss_price: float | None = None
    status: ReplicaPositionStatus = ReplicaPositionStatus.OPEN

    def __post_init__(self) -> None:
        if not str(self.position_id).strip():
            raise ValueError("position_id must not be empty")
        if not str(self.connection_id).strip():
            raise ValueError("connection_id must not be empty")
        if not str(self.source_intent_id).strip():
            raise ValueError("source_intent_id must not be empty")
        if not str(self.symbol).strip():
            raise ValueError("symbol must not be empty")
        if self.quantity <= 0.0:
            raise ValueError("quantity must be positive")
        if self.remaining_quantity < 0.0 or self.remaining_quantity > self.quantity + 1e-12:
            raise ValueError("remaining_quantity must be within [0, quantity]")
        if self.entry_price <= 0.0:
            raise ValueError("entry_price must be positive")

        if self.remaining_quantity <= 1e-12 and self.status is not ReplicaPositionStatus.CLOSED:
            object.__setattr__(self, "status", ReplicaPositionStatus.CLOSED)
        elif self.remaining_quantity < self.quantity - 1e-12 and self.status is ReplicaPositionStatus.OPEN:
            object.__setattr__(self, "status", ReplicaPositionStatus.PARTIALLY_CLOSED)

    @property
    def is_active(self) -> bool:
        return self.remaining_quantity > 1e-12 and self.status is not ReplicaPositionStatus.CLOSED

    def close_quantity(self, close_fraction: float) -> float:
        fraction = float(close_fraction)
        if not 0.0 < fraction <= 1.0:
            raise ValueError("close_fraction must be in (0, 1]")
        if not self.is_active:
            return 0.0
        return self.remaining_quantity * fraction


class ReplicaPositionStateStore:
    """Thread-safe in-memory state boundary for account-local replica positions."""

    def __init__(self) -> None:
        self._positions: dict[str, ReplicaPositionRecord] = {}
        self._lock = threading.RLock()

    def register(self, position: ReplicaPositionRecord) -> None:
        with self._lock:
            if position.position_id in self._positions:
                raise ValueError(f"replica position already exists: {position.position_id}")
            self._positions[position.position_id] = position

    def get(self, position_id: str) -> ReplicaPositionRecord | None:
        with self._lock:
            return self._positions.get(position_id)

    def by_source_intent(self, source_intent_id: str) -> tuple[ReplicaPositionRecord, ...]:
        source = str(source_intent_id).strip()
        with self._lock:
            return tuple(
                p for p in self._positions.values()
                if p.source_intent_id == source
            )

    def active_for_account(
        self,
        *,
        connection_id: str,
        source_intent_id: str,
    ) -> ReplicaPositionRecord | None:
        with self._lock:
            for position in self._positions.values():
                if (
                    position.connection_id == connection_id
                    and position.source_intent_id == source_intent_id
                    and position.is_active
                ):
                    return position
        return None

    def apply_close(
        self,
        *,
        position_id: str,
        executed_quantity: float,
    ) -> ReplicaPositionRecord:
        quantity = float(executed_quantity)
        if quantity <= 0.0:
            raise ValueError("executed_quantity must be positive")

        with self._lock:
            current = self._positions.get(position_id)
            if current is None:
                raise KeyError(f"replica position not found: {position_id}")
            if quantity > current.remaining_quantity + 1e-12:
                raise ValueError("executed_quantity exceeds remaining quantity")

            remaining = max(0.0, current.remaining_quantity - quantity)
            status = (
                ReplicaPositionStatus.CLOSED
                if remaining <= 1e-12
                else ReplicaPositionStatus.PARTIALLY_CLOSED
            )
            updated = ReplicaPositionRecord(
                position_id=current.position_id,
                connection_id=current.connection_id,
                source_intent_id=current.source_intent_id,
                symbol=current.symbol,
                quantity=current.quantity,
                remaining_quantity=remaining,
                entry_price=current.entry_price,
                stop_loss_price=current.stop_loss_price,
                status=status,
            )
            self._positions[position_id] = updated
            return updated

    def all(self) -> tuple[ReplicaPositionRecord, ...]:
        with self._lock:
            return tuple(self._positions.values())


__all__ = [
    "ReplicaPositionRecord",
    "ReplicaPositionStateStore",
    "ReplicaPositionStatus",
]
