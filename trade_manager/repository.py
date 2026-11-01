"""8.2 - Thread-safe position repository with optional restart persistence.

Persistence is deliberately owned by the repository boundary: callers keep the
same Position API and never manipulate storage directly. The state file is a
local application artifact and is written atomically.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import asdict
from enum import Enum
from typing import Any, Dict, List, Optional

from .models import Position, PositionCloseReason, PositionSide, PositionStatus


def _encode(value: Any) -> Any:
    if isinstance(value, Enum):
        return {"__enum__": f"{type(value).__name__}:{value.name}"}
    if isinstance(value, dict):
        return {str(k): _encode(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_encode(v) for v in value]
    return value


def _decode_enum(value: Any) -> Any:
    if not isinstance(value, dict) or "__enum__" not in value:
        return value
    enum_type, member = value["__enum__"].split(":", 1)
    enums = {
        "PositionStatus": PositionStatus,
        "PositionSide": PositionSide,
        "PositionCloseReason": PositionCloseReason,
    }
    return enums[enum_type][member]


def _decode(value: Any) -> Any:
    if isinstance(value, dict):
        enum_value = _decode_enum(value)
        if enum_value is not value:
            return enum_value
        return {k: _decode(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_decode(v) for v in value]
    return value


class PositionRepository:
    def __init__(self, persistence_path: Optional[str] = None) -> None:
        self._positions: Dict[str, Position] = {}
        self._lock = threading.RLock()
        self.persistence_path = persistence_path
        if self.persistence_path:
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
            symbol = symbol.upper()
            return [p for p in self._positions.values() if p.symbol.upper() == symbol]

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

    def flush(self) -> None:
        with self._lock:
            self._persist_locked()

    def export_snapshot(
        self,
        *,
        closed_since_epoch: float | None = None,
    ) -> dict[str, Any]:
        """Return a versioned, JSON-safe snapshot for an external state store.

        When a cutoff is supplied, preserve all active positions and only the
        closed positions needed to rebuild current daily/weekly/monthly risk
        ledgers. Full historical outcomes belong in the append-only evidence
        store, not in the mutable runtime-state snapshot.
        """
        with self._lock:
            positions = list(self._positions.values())
            if closed_since_epoch is not None:
                cutoff = float(closed_since_epoch)
                positions = [
                    position
                    for position in positions
                    if position.status is not PositionStatus.CLOSED
                    or float(position.closed_at or position.opened_at) >= cutoff
                ]
            return {
                "version": 1,
                "positions": [
                    _encode(asdict(position))
                    for position in positions
                ],
            }

    def restore_snapshot(self, payload: dict[str, Any]) -> None:
        """Restore positions from a validated external snapshot."""
        if not isinstance(payload, dict) or payload.get("version") != 1:
            raise ValueError("unsupported position state version")
        restored: Dict[str, Position] = {}
        for raw in payload.get("positions", []):
            if not isinstance(raw, dict):
                raise ValueError("position snapshot entries must be objects")
            data = _decode(raw)
            position = Position(**data)
            if position.position_id in restored:
                raise ValueError(f"duplicate position id in snapshot: {position.position_id}")
            restored[position.position_id] = position
        with self._lock:
            self._positions = restored
            self._persist_locked()

    def _persist_locked(self) -> None:
        if not self.persistence_path:
            return
        directory = os.path.dirname(os.path.abspath(self.persistence_path))
        os.makedirs(directory, exist_ok=True)
        payload = {
            "version": 1,
            "positions": [_encode(asdict(position)) for position in self._positions.values()],
        }
        fd, temp_path = tempfile.mkstemp(prefix="positions-", suffix=".tmp", dir=directory)
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
            if payload.get("version") != 1:
                raise ValueError("unsupported position state version")
            restored: Dict[str, Position] = {}
            for raw in payload.get("positions", []):
                data = _decode(raw)
                position = Position(**data)
                restored[position.position_id] = position
            self._positions = restored
        except Exception as exc:
            raise RuntimeError(f"Unable to restore PositionRepository: {exc}") from exc
