"""Single account-scoped replica-position state contract.

This module stores replica linkage and persistence while reusing the canonical
Trade Manager PositionStatus lifecycle. It does not decide strategy, risk, or
when a position should close.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import json
import os
import tempfile
import threading
import time
from typing import Optional

from trade_manager.models import PositionStatus

# Compatibility name for existing callers/tests; lifecycle authority remains TM.
ReplicaPositionStatus = PositionStatus


@dataclass(frozen=True, slots=True)
class ReplicaPositionRecord:
    """Account-local position derived from one shared master OPEN intent."""

    position_id: str
    connection_id: str
    source_intent_id: str
    symbol: str
    quantity: float
    remaining_quantity: float
    entry_price: float
    stop_loss_price: float | None = None
    status: PositionStatus = PositionStatus.OPEN
    master_position_id: str = ""
    user_position_id: str = ""
    idempotency_key: str = ""
    opened_at: float = 0.0
    updated_at: float = 0.0
    closed_at: Optional[float] = None
    close_intent_id: Optional[str] = None
    master_close_position_id: Optional[str] = None
    client_order_id: Optional[str] = None
    exchange_order_id: Optional[str] = None

    def __post_init__(self) -> None:
        for name in ("position_id", "connection_id", "source_intent_id", "symbol"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} must not be empty")
        if self.quantity <= 0.0:
            raise ValueError("quantity must be positive")
        if self.remaining_quantity < 0.0 or self.remaining_quantity > self.quantity + 1e-12:
            raise ValueError("remaining_quantity must be within [0, quantity]")
        if self.entry_price <= 0.0:
            raise ValueError("entry_price must be positive")

        now = time.time()
        master_position_id = self.master_position_id.strip() or self.position_id
        user_position_id = self.user_position_id.strip() or self.position_id
        idempotency_key = (
            self.idempotency_key.strip()
            or self.make_idempotency_key(self.source_intent_id, self.connection_id, "OPEN")
        )
        opened_at = self.opened_at or now
        updated_at = self.updated_at or opened_at

        object.__setattr__(self, "master_position_id", master_position_id)
        object.__setattr__(self, "user_position_id", user_position_id)
        object.__setattr__(self, "idempotency_key", idempotency_key)
        object.__setattr__(self, "opened_at", opened_at)
        object.__setattr__(self, "updated_at", updated_at)

        if self.remaining_quantity <= 1e-12:
            object.__setattr__(self, "status", PositionStatus.CLOSED)
        elif self.remaining_quantity < self.quantity - 1e-12 and self.status is PositionStatus.OPEN:
            object.__setattr__(self, "status", PositionStatus.PARTIALLY_CLOSED)

    @staticmethod
    def make_idempotency_key(intent_id: str, account_id: str, action: str) -> str:
        return f"{intent_id.strip()}:{account_id.strip()}:{action.strip().upper()}"

    @property
    def is_active(self) -> bool:
        return (
            self.remaining_quantity > 1e-12
            and self.status not in {
                PositionStatus.CLOSED,
                PositionStatus.CANCELLED,
                PositionStatus.FAILED,
            }
        )

    def close_quantity(self, close_fraction: float) -> float:
        fraction = float(close_fraction)
        if not 0.0 < fraction <= 1.0:
            raise ValueError("close_fraction must be in (0, 1]")
        if not self.is_active:
            return 0.0
        return self.remaining_quantity * fraction


class ReplicaPositionStateStore:
    """Thread-safe state boundary with optional atomic restart persistence."""

    def __init__(self, persistence_path: str | None = None) -> None:
        self.persistence_path = persistence_path
        self._positions: dict[str, ReplicaPositionRecord] = {}
        self._lock = threading.RLock()
        if persistence_path:
            self._load()

    def register(self, position: ReplicaPositionRecord) -> None:
        with self._lock:
            if position.position_id in self._positions:
                raise ValueError(f"replica position already exists: {position.position_id}")
            self._positions[position.position_id] = position
            self._persist_locked()

    def get(self, position_id: str) -> ReplicaPositionRecord | None:
        with self._lock:
            return self._positions.get(position_id)

    def get_by_idempotency_key(self, idempotency_key: str) -> ReplicaPositionRecord | None:
        key = str(idempotency_key).strip()
        if not key:
            return None
        with self._lock:
            for position in self._positions.values():
                if position.idempotency_key == key:
                    return position
        return None

    def by_source_intent(self, source_intent_id: str) -> tuple[ReplicaPositionRecord, ...]:
        source = str(source_intent_id).strip()
        with self._lock:
            return tuple(p for p in self._positions.values() if p.source_intent_id == source)

    def by_master_position(
        self,
        master_position_id: str,
        connection_id: str | None = None,
    ) -> tuple[ReplicaPositionRecord, ...]:
        master = str(master_position_id).strip()
        with self._lock:
            return tuple(
                p for p in self._positions.values()
                if p.master_position_id == master
                and (connection_id is None or p.connection_id == connection_id)
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
                    and position.source_intent_id == str(source_intent_id).strip()
                    and position.is_active
                ):
                    return position
        return None

    def close_applied_for_master_position(
        self,
        *,
        connection_id: str,
        master_position_id: str,
        close_intent_id: str,
    ) -> bool:
        close_id = str(close_intent_id).strip()
        master = str(master_position_id).strip()
        with self._lock:
            return any(
                position.connection_id == connection_id
                and position.master_position_id == master
                and position.close_intent_id == close_id
                for position in self._positions.values()
            )

    def active_for_master_position(
        self,
        *,
        connection_id: str,
        master_position_id: str,
    ) -> ReplicaPositionRecord | None:
        with self._lock:
            for position in self._positions.values():
                if (
                    position.connection_id == connection_id
                    and position.master_position_id == str(master_position_id).strip()
                    and position.is_active
                ):
                    return position
        return None

    def apply_close(
        self,
        *,
        position_id: str,
        executed_quantity: float,
        close_intent_id: str | None = None,
        master_close_position_id: str | None = None,
        exchange_order_id: str | None = None,
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
                PositionStatus.CLOSED
                if remaining <= 1e-12
                else PositionStatus.PARTIALLY_CLOSED
            )
            now = time.time()
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
                master_position_id=current.master_position_id,
                user_position_id=current.user_position_id,
                idempotency_key=current.idempotency_key,
                opened_at=current.opened_at,
                updated_at=now,
                closed_at=now if status is PositionStatus.CLOSED else None,
                close_intent_id=close_intent_id or current.close_intent_id,
                master_close_position_id=master_close_position_id or (
                    current.master_close_position_id if status is PositionStatus.CLOSED else None
                ),
                client_order_id=current.client_order_id,
                exchange_order_id=exchange_order_id or current.exchange_order_id,
            )
            self._positions[position_id] = updated
            self._persist_locked()
            return updated

    def all(self) -> tuple[ReplicaPositionRecord, ...]:
        with self._lock:
            return tuple(self._positions.values())

    @staticmethod
    def _encode(value):
        if isinstance(value, Enum):
            return {"__enum__": f"{type(value).__name__}:{value.name}"}
        if isinstance(value, dict):
            return {str(k): ReplicaPositionStateStore._encode(v) for k, v in value.items()}
        if isinstance(value, list):
            return [ReplicaPositionStateStore._encode(v) for v in value]
        return value

    @staticmethod
    def _decode(value):
        if isinstance(value, dict):
            marker = value.get("__enum__")
            if marker:
                enum_type, member = marker.split(":", 1)
                if enum_type in {"PositionStatus", "ReplicaPositionStatus"}:
                    return PositionStatus[member]
            return {k: ReplicaPositionStateStore._decode(v) for k, v in value.items()}
        if isinstance(value, list):
            return [ReplicaPositionStateStore._decode(v) for v in value]
        return value

    def _persist_locked(self) -> None:
        if not self.persistence_path:
            return
        directory = os.path.dirname(os.path.abspath(self.persistence_path))
        os.makedirs(directory, exist_ok=True)
        payload = {
            "version": 2,
            "positions": [
                self._encode(asdict(position))
                for position in self._positions.values()
            ],
        }
        fd, temp_path = tempfile.mkstemp(
            prefix="replica-position-state-",
            suffix=".tmp",
            dir=directory,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self.persistence_path)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    def _load(self) -> None:
        if not os.path.exists(self.persistence_path):
            return
        try:
            with open(self.persistence_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            if payload.get("version") not in {1, 2}:
                raise ValueError("unsupported replica position state version")
            restored: dict[str, ReplicaPositionRecord] = {}
            for raw in payload.get("positions", []):
                data = self._decode(raw)
                if payload.get("version") == 1:
                    data.setdefault("master_position_id", data.get("position_id", ""))
                    data.setdefault("user_position_id", data.get("position_id", ""))
                position = ReplicaPositionRecord(**data)
                restored[position.position_id] = position
            self._positions = restored
        except Exception as exc:
            raise RuntimeError(f"Unable to restore ReplicaPositionStateStore: {exc}") from exc


__all__ = [
    "ReplicaPositionRecord",
    "ReplicaPositionStateStore",
    "ReplicaPositionStatus",
]
