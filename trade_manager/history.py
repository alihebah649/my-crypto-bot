"""8.8 - Closed-position history and archival."""
from dataclasses import dataclass, field
import threading
import time
from typing import Dict, List, Optional
from .models import Position, PositionCloseReason, PositionSide, PositionStatus


@dataclass(slots=True)
class PositionHistoryRecord:
    position_id: str
    symbol: str
    side: str
    quantity: float
    entry_price: float
    exit_price: float
    stop_loss: float
    take_profit: Optional[float]
    highest_price: float
    lowest_price: float
    max_profit_percent: float
    max_drawdown_percent: float
    opened_at: float
    closed_at: Optional[float]
    close_reason: str
    gross_pnl: float
    realized_pnl: float
    total_fees: float
    entry_fee: float
    exit_fee: float
    holding_hours: float
    roi_percent: float
    entry_metadata: dict = field(default_factory=dict)
    exit_metadata: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
    archived_at: float = field(default_factory=time.time)


class PositionHistoryRepository:
    def __init__(self):
        self._records: Dict[str, PositionHistoryRecord] = {}
        self._lock = threading.RLock()

    def add_record(self, record: PositionHistoryRecord) -> None:
        with self._lock:
            self._records[record.position_id] = record

    def get_all_records(self) -> List[PositionHistoryRecord]:
        with self._lock:
            return list(self._records.values())


class PositionHistoryService:
    def __init__(self, calculator=None):
        self.repository = PositionHistoryRepository()

    def record_closed_position(self, position: Position) -> PositionHistoryRecord:
        if position.status != PositionStatus.CLOSED:
            raise ValueError("only CLOSED positions can be archived")
        closed_at = position.closed_at or time.time()
        cost = position.entry_price * position.quantity
        record = PositionHistoryRecord(
            position_id=position.position_id, symbol=position.symbol, side=position.side.name,
            quantity=position.quantity, entry_price=position.entry_price,
            exit_price=position.current_price, stop_loss=position.stop_loss,
            take_profit=position.take_profit, highest_price=position.highest_price,
            lowest_price=position.lowest_price, max_profit_percent=position.max_profit_percent,
            max_drawdown_percent=position.max_drawdown_percent, opened_at=position.opened_at,
            closed_at=closed_at, close_reason=position.close_reason.name,
            gross_pnl=position.gross_pnl, realized_pnl=position.realized_pnl,
            total_fees=position.total_fees, entry_fee=position.entry_fee,
            exit_fee=position.exit_fee, holding_hours=(closed_at-position.opened_at)/3600.0,
            roi_percent=(position.realized_pnl/cost*100.0 if cost else 0.0),
            entry_metadata=dict(position.entry_metadata), exit_metadata=dict(position.exit_metadata),
            metadata=dict(position.metadata))
        self.repository.add_record(record)
        return record

    def get_all_closed_positions(self) -> List[Position]:
        result = []
        for r in self.repository.get_all_records():
            result.append(Position(
                position_id=r.position_id, symbol=r.symbol, side=PositionSide.LONG,
                status=PositionStatus.CLOSED, quantity=r.quantity, entry_price=r.entry_price,
                current_price=r.exit_price, stop_loss=r.stop_loss, take_profit=r.take_profit,
                highest_price=r.highest_price, lowest_price=r.lowest_price,
                max_profit_percent=r.max_profit_percent, max_drawdown_percent=r.max_drawdown_percent,
                opened_at=r.opened_at, closed_at=r.closed_at,
                close_reason=PositionCloseReason[r.close_reason],
                gross_pnl=r.gross_pnl, realized_pnl=r.realized_pnl, total_fees=r.total_fees,
                entry_fee=r.entry_fee, exit_fee=r.exit_fee,
                entry_metadata=dict(r.entry_metadata), exit_metadata=dict(r.exit_metadata),
                metadata=dict(r.metadata)))
        return result
