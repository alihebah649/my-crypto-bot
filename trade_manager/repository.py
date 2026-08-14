"""8.2 - Thread-safe position repository with optional durable persistence.

Persistence is deliberately opt-in. Unit/integration tests can keep the
in-memory repository, while the Paper Trading application supplies a state
path so an application restart cannot silently forget owned positions.
"""
from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict
from enum import Enum
from typing import Any, Dict, List, Optional

from .models import Position, PositionSide, PositionStatus, PositionCloseReason


class PositionRepository:
    def __init__(self, state_path: Optional[str] = None) -> None:
        self._positions: Dict[str, Position] = {}
        self._lock = threading.RLock()
        self.state_path = state_path
        if state_path:
            self._load()

    def add(self, position: Position) -> None:
        with self._lock:
            if position.position_id in self._positions:
                raise ValueError(f"Position already exists: {position.position_id}")
            self._positions[position.position_id] = position
            self._persist_locked()

    def update(self, position: Position) -> None:
        with self._lock:
            self._positions[position.position_id] = position
            self._persist_locked()

    def get(self, position_id: str) -> Optional[Position]:
        with self._lock:
            return self._positions.get(position_id)

    def get_by_symbol(self, symbol: str) -> List[Position]:
        with self._lock:
            return [p for p in self._positions.values() if p.symbol == symbol]

    def get_open_positions(self) -> List[Position]:
        with self._lock:
            active = {PositionStatus.OPEN, PositionStatus.PARTIALLY_CLOSED,
                      PositionStatus.HOLD, PositionStatus.REVIEW_REQUIRED}
            return [p for p in self._positions.values() if p.status in active]

    def get_hold_positions(self) -> List[Position]:
        with self._lock:
            return [p for p in self._positions.values() if p.status == PositionStatus.HOLD]

    def get_review_required(self) -> List[Position]:
        with self._lock:
            return [p for p in self._positions.values() if p.status == PositionStatus.REVIEW_REQUIRED]

    def get_closed_positions(self) -> List[Position]:
        with self._lock:
            return [p for p in self._positions.values() if p.status == PositionStatus.CLOSED]

    def get_all(self) -> List[Position]:
        with self._lock:
            return list(self._positions.values())

    def clear(self) -> None:
        with self._lock:
            self._positions.clear()
            self._persist_locked()

    def count(self) -> int:
        with self._lock:
            return len(self._positions)

    def persist(self) -> None:
        with self._lock:
            self._persist_locked()

    @staticmethod
    def _encode(value: Any) -> Any:
        if isinstance(value, Enum):
            return {"__enum__": f"{value.__class__.__name__}:{value.name}"}
        if isinstance(value, dict):
            return {str(k): PositionRepository._encode(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [PositionRepository._encode(v) for v in value]
        return value

    @staticmethod
    def _decode(value: Any) -> Any:
        if isinstance(value, list):
            return [PositionRepository._decode(v) for v in value]
        if isinstance(value, dict):
            marker = value.get("__enum__")
            if marker:
                enum_name, member = marker.split(":", 1)
                enums = {
                    "PositionSide": PositionSide,
                    "PositionStatus": PositionStatus,
                    "PositionCloseReason": PositionCloseReason,
                }
                return enums[enum_name][member]
            return {k: PositionRepository._decode(v) for k, v in value.items()}
        return value

    def _serialize_position(self, position: Position) -> dict:
        return self._encode(asdict(position))

    def _deserialize_position(self, payload: dict) -> Position:
        return Position(**self._decode(payload))

    def _persist_locked(self) -> None:
        if not self.state_path:
            return
        directory = os.path.dirname(os.path.abspath(self.state_path))
        os.makedirs(directory, exist_ok=True)
        payload = {
            "version": 1,
            "positions": [self._serialize_position(p) for p in self._positions.values()],
        }
        temporary = f"{self.state_path}.tmp"
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self.state_path)

    def _load(self) -> None:
        if not self.state_path or not os.path.exists(self.state_path):
            return
        with self._lock:
            try:
                with open(self.state_path, "r", encoding="utf-8") as handle:
                    payload = json.load(handle)
                if payload.get("version") != 1:
                    raise ValueError(f"Unsupported Trade Manager state version: {payload.get('version')}")
                restored = {}
                for item in payload.get("positions", []):
                    position = self._deserialize_position(item)
                    restored[position.position_id] = position
                self._positions = restored
            except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
                # Fail closed: a corrupt state file must not be silently treated
                # as a valid empty portfolio. The caller can inspect the error.
                raise RuntimeError(f"Unable to restore Trade Manager state from {self.state_path}")
