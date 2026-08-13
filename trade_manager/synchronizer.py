"""8.6 - Exchange/local position synchronization."""
from dataclasses import dataclass, field
from enum import Enum, auto
import threading
import time
from typing import Any, Dict, List, Optional
from uuid import uuid4
from .calculator import PositionCalculator
from .controller import PositionController
from .models import Position, PositionCloseReason, PositionSide, PositionStatus
from .repository import PositionRepository


class SynchronizationStatus(Enum):
    IDLE = auto(); RUNNING = auto(); SUCCESS = auto(); PARTIAL = auto(); FAILED = auto()


class SynchronizationEventType(Enum):
    POSITION_CREATED = auto(); POSITION_UPDATED = auto(); POSITION_CLOSED = auto()
    POSITION_IMPORTED = auto(); LOCAL_ONLY = auto(); SYNC_UNCERTAIN = auto(); ERROR = auto()


@dataclass(slots=True)
class ExchangePosition:
    symbol: str
    quantity: float
    entry_price: float
    current_price: float
    side: PositionSide = PositionSide.LONG
    stop_loss: float = 0.0
    take_profit: Optional[float] = None
    exchange_order_id: Optional[str] = None
    client_order_id: Optional[str] = None
    opened_at: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SynchronizationEvent:
    event_id: str
    event_type: SynchronizationEventType
    position_id: Optional[str]
    symbol: Optional[str]
    message: str
    timestamp: float = field(default_factory=time.time)


@dataclass(slots=True)
class SynchronizationResult:
    status: SynchronizationStatus
    started_at: float
    completed_at: float
    created: int = 0
    updated: int = 0
    closed: int = 0
    imported: int = 0
    local_only: int = 0
    sync_uncertain: int = 0
    errors: int = 0
    events: List[SynchronizationEvent] = field(default_factory=list)


class ExchangePositionAdapter:
    def get_open_positions(self) -> List[ExchangePosition]:
        raise NotImplementedError


class MemoryExchangePositionAdapter(ExchangePositionAdapter):
    def __init__(self):
        self._positions: Dict[str, ExchangePosition] = {}
        self._lock = threading.RLock()

    def get_open_positions(self) -> List[ExchangePosition]:
        with self._lock:
            return list(self._positions.values())


class PositionSynchronizer:
    MAX_RETRIES = 3
    RETRY_DELAY = 1.0

    def __init__(self, repository: PositionRepository, controller: PositionController,
                 calculator: PositionCalculator, exchange_adapter: ExchangePositionAdapter):
        self.repository = repository
        self.controller = controller
        self.calculator = calculator
        self.exchange_adapter = exchange_adapter
        self._lock = threading.RLock()
        self._status = SynchronizationStatus.IDLE
        self._last_result: Optional[SynchronizationResult] = None
        self._missing_positions: Dict[str, int] = {}

    def synchronize(self) -> SynchronizationResult:
        started = time.time()
        with self._lock:
            if self._status == SynchronizationStatus.RUNNING:
                return SynchronizationResult(SynchronizationStatus.FAILED, started, time.time(), errors=1)
            self._status = SynchronizationStatus.RUNNING
        events: List[SynchronizationEvent] = []
        try:
            exchange = self.exchange_adapter.get_open_positions() or []
            local = self.repository.get_open_positions()
            result = SynchronizationResult(SynchronizationStatus.SUCCESS, started, 0.0, events=events)
            for ex in exchange:
                try:
                    lp = self._find_matching(ex, local)
                    if lp is None:
                        self._import_position(ex)
                        result.created += 1; result.imported += 1
                    elif self._update_position(lp, ex):
                        result.updated += 1
                except Exception as exc:
                    result.errors += 1
                    events.append(SynchronizationEvent(str(uuid4()), SynchronizationEventType.ERROR,
                                                        None, ex.symbol, f"Sync error: {exc}"))
            for lp in local:
                if self._find_exchange(lp, exchange) is None:
                    count = self._missing_positions.get(lp.position_id, 0) + 1
                    self._missing_positions[lp.position_id] = count
                    if count >= self.MAX_RETRIES:
                        self._close_missing(lp)
                        result.closed += 1; result.local_only += 1
                        self._missing_positions.pop(lp.position_id, None)
                    else:
                        result.sync_uncertain += 1
                        events.append(SynchronizationEvent(str(uuid4()), SynchronizationEventType.SYNC_UNCERTAIN,
                                                            lp.position_id, lp.symbol,
                                                            f"Missing from exchange ({count}/{self.MAX_RETRIES})"))
            result.status = SynchronizationStatus.PARTIAL if result.errors else SynchronizationStatus.SUCCESS
            result.completed_at = time.time()
            with self._lock:
                self._last_result = result; self._status = result.status
            return result
        except Exception:
            result = SynchronizationResult(SynchronizationStatus.FAILED, started, time.time(), errors=1, events=events)
            with self._lock:
                self._last_result = result; self._status = SynchronizationStatus.FAILED
            return result

    @staticmethod
    def _find_matching(ex: ExchangePosition, local: List[Position]) -> Optional[Position]:
        if ex.exchange_order_id:
            for p in local:
                if p.exchange_order_id == ex.exchange_order_id: return p
        if ex.client_order_id:
            for p in local:
                if p.client_order_id == ex.client_order_id: return p
        candidates = [p for p in local if p.symbol == ex.symbol]
        return min(candidates, key=lambda p: abs(p.entry_price - ex.entry_price)) if candidates else None

    @staticmethod
    def _find_exchange(local: Position, exchange: List[ExchangePosition]) -> Optional[ExchangePosition]:
        if local.exchange_order_id:
            for p in exchange:
                if p.exchange_order_id == local.exchange_order_id: return p
        if local.client_order_id:
            for p in exchange:
                if p.client_order_id == local.client_order_id: return p
        candidates = [p for p in exchange if p.symbol == local.symbol]
        return min(candidates, key=lambda p: abs(p.entry_price - local.entry_price)) if candidates else None

    def _import_position(self, ex: ExchangePosition) -> Position:
        p = Position(position_id=f"SYNC-{uuid4().hex[:8]}", symbol=ex.symbol,
                     side=PositionSide.LONG, status=PositionStatus.OPEN, quantity=ex.quantity,
                     entry_price=ex.entry_price, current_price=ex.current_price,
                     stop_loss=ex.stop_loss or ex.entry_price * 0.95, take_profit=ex.take_profit,
                     exchange_order_id=ex.exchange_order_id, client_order_id=ex.client_order_id,
                     opened_at=ex.opened_at or time.time())
        p.metadata["imported_from_exchange"] = True
        p.metadata["imported_at"] = time.time()
        self.repository.add(p)
        return p

    def _update_position(self, local: Position, ex: ExchangePosition) -> bool:
        changed = False
        if local.current_price != ex.current_price:
            local.current_price = ex.current_price; changed = True
        if local.quantity != ex.quantity:
            local.quantity = ex.quantity; changed = True
        if changed:
            local.update_highest_price(ex.current_price); local.update_lowest_price(ex.current_price)
            self.repository.update(local)
        return changed

    def _close_missing(self, position: Position) -> None:
        if position.status in {PositionStatus.CLOSED, PositionStatus.CANCELLED}: return
        position.status = PositionStatus.CLOSED
        position.closed_at = time.time()
        position.close_reason = PositionCloseReason.EMERGENCY_EXIT
        result = self.calculator.calculate(position, position.current_price)
        position.gross_pnl = result.gross_pnl; position.realized_pnl = result.net_pnl
        position.total_fees = result.total_fees; position.entry_fee = result.entry_fee; position.exit_fee = result.exit_fee
        self.repository.update(position)

    def reset_missing_tracking(self) -> None:
        with self._lock: self._missing_positions.clear()
