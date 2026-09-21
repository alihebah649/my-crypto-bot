"""Account-scoped replica position state built on the Trade Manager lifecycle.

This is linkage/state, not a second position lifecycle. Status values are the
canonical Trade Manager PositionStatus enum.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import Optional

from trade_manager.models import PositionStatus


@dataclass(slots=True)
class ReplicaPosition:
    account_id: str
    master_intent_id: str
    master_position_id: str
    user_position_id: str
    symbol: str
    quantity: float
    entry_price: float
    stop_loss: float | None
    status: PositionStatus = PositionStatus.CREATED
    idempotency_key: str = ""
    opened_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    closed_at: Optional[float] = None
    close_intent_id: Optional[str] = None
    master_close_position_id: Optional[str] = None
    exchange_order_id: Optional[str] = None
    client_order_id: Optional[str] = None
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.account_id.strip():
            raise ValueError("account_id must not be empty")
        if not self.master_intent_id.strip():
            raise ValueError("master_intent_id must not be empty")
        if not self.master_position_id.strip():
            raise ValueError("master_position_id must not be empty")
        if not self.user_position_id.strip():
            raise ValueError("user_position_id must not be empty")
        if not self.symbol.strip():
            raise ValueError("symbol must not be empty")
        if self.quantity <= 0 or self.entry_price <= 0:
            raise ValueError("quantity and entry_price must be positive")
        if not self.idempotency_key:
            self.idempotency_key = self.make_idempotency_key(
                self.master_intent_id, self.account_id, "OPEN"
            )

    @staticmethod
    def make_idempotency_key(master_intent_id: str, account_id: str, action: str) -> str:
        return f"{master_intent_id.strip()}:{account_id.strip()}:{action.strip().upper()}"

    @classmethod
    def from_open(
        cls,
        *,
        account_id: str,
        master_intent_id: str,
        master_position_id: str,
        symbol: str,
        quantity: float,
        entry_price: float,
        stop_loss: float | None,
        client_order_id: str = "",
        exchange_order_id: str = "",
        metadata: dict | None = None,
    ) -> "ReplicaPosition":
        now = time.time()
        return cls(
            account_id=account_id,
            master_intent_id=master_intent_id,
            master_position_id=master_position_id,
            user_position_id=f"POS-{account_id}-{master_position_id}",
            symbol=symbol.upper(),
            quantity=quantity,
            entry_price=entry_price,
            stop_loss=stop_loss,
            status=PositionStatus.OPEN,
            idempotency_key=cls.make_idempotency_key(master_intent_id, account_id, "OPEN"),
            opened_at=now,
            updated_at=now,
            client_order_id=client_order_id or None,
            exchange_order_id=exchange_order_id or None,
            metadata=dict(metadata or {}),
        )

    def mark_closed(self, *, close_intent_id: str, exchange_order_id: str = "") -> None:
        if self.status is PositionStatus.CLOSED:
            return
        self.status = PositionStatus.CLOSED
        self.close_intent_id = close_intent_id
        self.master_close_position_id = self.master_position_id
        self.exchange_order_id = exchange_order_id or self.exchange_order_id
        self.closed_at = time.time()
        self.updated_at = self.closed_at
