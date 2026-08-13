"""8.2 - Thread-safe position repository."""
import threading
from typing import Dict, List, Optional
from .models import Position, PositionStatus


class PositionRepository:
    def __init__(self) -> None:
        self._positions: Dict[str, Position] = {}
        self._lock = threading.RLock()

    def add(self, position: Position) -> None:
        with self._lock:
            if position.position_id in self._positions:
                raise ValueError(f"Position already exists: {position.position_id}")
            self._positions[position.position_id] = position

    def update(self, position: Position) -> None:
        with self._lock:
            self._positions[position.position_id] = position

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

    def count(self) -> int:
        with self._lock:
            return len(self._positions)
