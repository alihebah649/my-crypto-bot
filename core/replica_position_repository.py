"""Persistent repository for account-scoped replica positions."""
from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import asdict
from enum import Enum
from typing import Optional

from trade_manager.models import PositionStatus
from core.replica_position import ReplicaPosition


def _encode(value):
    if isinstance(value, Enum):
        return {"__enum__": f"{type(value).__name__}:{value.name}"}
    if isinstance(value, dict):
        return {str(k): _encode(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_encode(v) for v in value]
    return value


def _decode(value):
    if isinstance(value, dict):
        marker = value.get("__enum__")
        if marker:
            enum_type, member = marker.split(":", 1)
            if enum_type == "PositionStatus":
                return PositionStatus[member]
        return {k: _decode(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_decode(v) for v in value]
    return value


class ReplicaPositionRepository:
    """Thread-safe, atomic, restart-safe storage for replica positions."""

    def __init__(self, persistence_path: Optional[str] = None):
        self.persistence_path = persistence_path
        self._positions: dict[str, ReplicaPosition] = {}
        self._lock = threading.RLock()
        if persistence_path:
            self._load()

    def add(self, position: ReplicaPosition) -> None:
        with self._lock:
            if position.user_position_id in self._positions:
                raise ValueError(f"Replica position already exists: {position.user_position_id}")
            self._positions[position.user_position_id] = position
            self._persist_locked()

    def upsert(self, position: ReplicaPosition) -> ReplicaPosition:
        with self._lock:
            self._positions[position.user_position_id] = position
            self._persist_locked()
            return position

    def get(self, user_position_id: str) -> Optional[ReplicaPosition]:
        with self._lock:
            return self._positions.get(user_position_id)

    def get_by_master_position(self, master_position_id: str, account_id: str | None = None) -> list[ReplicaPosition]:
        with self._lock:
            return [
                p for p in self._positions.values()
                if p.master_position_id == master_position_id
                and (account_id is None or p.account_id == account_id)
            ]

    def get_open_for_account(self, account_id: str, symbol: str | None = None) -> list[ReplicaPosition]:
        with self._lock:
            return [
                p for p in self._positions.values()
                if p.account_id == account_id
                and p.status in {
                    PositionStatus.OPEN,
                    PositionStatus.PARTIALLY_CLOSED,
                    PositionStatus.HOLD,
                    PositionStatus.REVIEW_REQUIRED,
                }
                and (symbol is None or p.symbol.upper() == symbol.upper())
            ]

    def all(self) -> tuple[ReplicaPosition, ...]:
        with self._lock:
            return tuple(self._positions.values())

    def _persist_locked(self) -> None:
        if not self.persistence_path:
            return
        directory = os.path.dirname(os.path.abspath(self.persistence_path))
        os.makedirs(directory, exist_ok=True)
        payload = {"version": 1, "positions": [_encode(asdict(p)) for p in self._positions.values()]}
        fd, tmp = tempfile.mkstemp(prefix="replica-positions-", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self.persistence_path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def _load(self) -> None:
        if not os.path.exists(self.persistence_path):
            return
        try:
            with open(self.persistence_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            if payload.get("version") != 1:
                raise ValueError("unsupported replica position state version")
            self._positions = {}
            for raw in payload.get("positions", []):
                position = ReplicaPosition(**_decode(raw))
                self._positions[position.user_position_id] = position
        except Exception as exc:
            raise RuntimeError(f"Unable to restore ReplicaPositionRepository: {exc}") from exc
