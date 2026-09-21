"""Idempotent delivery ledger for replicated trade intents.

A shared master intent may be retried after a process restart, network timeout,
or worker retry. This module creates one deterministic delivery key per
(intent, follower, action) so the orchestration layer can safely retry without
creating duplicate execution instructions.

This is not an exactly-once exchange guarantee; exchange execution still needs
client-order-id/idempotency handling and reconciliation at the execution layer.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class DeliveryState(str, Enum):
    NEW = "NEW"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class DeliveryRecord:
    delivery_key: str
    intent_id: str
    connection_id: str
    action: str
    state: DeliveryState = DeliveryState.NEW


class ReplicationDeliveryLedger:
    """In-memory idempotency boundary; durable storage comes later."""

    def __init__(self) -> None:
        self._records: dict[str, DeliveryRecord] = {}

    @staticmethod
    def make_key(
        *,
        intent_id: str,
        connection_id: str,
        action: str,
    ) -> str:
        intent = str(intent_id).strip()
        connection = str(connection_id).strip()
        normalized_action = str(action).strip().upper()

        if not intent:
            raise ValueError("intent_id must not be empty")
        if not connection:
            raise ValueError("connection_id must not be empty")
        if not normalized_action:
            raise ValueError("action must not be empty")

        return f"{intent}:{connection}:{normalized_action}"

    def register_new(
        self,
        *,
        intent_id: str,
        connection_id: str,
        action: str,
    ) -> DeliveryRecord:
        key = self.make_key(
            intent_id=intent_id,
            connection_id=connection_id,
            action=action,
        )
        existing = self._records.get(key)
        if existing is not None:
            return existing

        record = DeliveryRecord(
            delivery_key=key,
            intent_id=intent_id,
            connection_id=connection_id,
            action=str(action).strip().upper(),
        )
        self._records[key] = record
        return record

    def transition(
        self,
        delivery_key: str,
        state: DeliveryState,
    ) -> DeliveryRecord:
        try:
            current = self._records[delivery_key]
        except KeyError as exc:
            raise KeyError(f"delivery not registered: {delivery_key}") from exc

        updated = DeliveryRecord(
            delivery_key=current.delivery_key,
            intent_id=current.intent_id,
            connection_id=current.connection_id,
            action=current.action,
            state=state,
        )
        self._records[delivery_key] = updated
        return updated

    def get(self, delivery_key: str) -> DeliveryRecord | None:
        return self._records.get(delivery_key)

    def contains(self, delivery_key: str) -> bool:
        return delivery_key in self._records

    def all(self) -> tuple[DeliveryRecord, ...]:
        return tuple(self._records.values())


__all__ = [
    "DeliveryRecord",
    "DeliveryState",
    "ReplicationDeliveryLedger",
]
