from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("TradeManager.Recovery")


@dataclass(slots=True)
class RecoveryReport:
    database_positions: int = 0
    broker_positions: int = 0
    restored_positions: int = 0
    missing_on_broker: list[str] = field(default_factory=list)
    missing_in_database: list[str] = field(default_factory=list)
    duplicated_positions: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    success: bool = False


class RecoveryManager:
    """Restores internal state; it never opens, closes, or modifies trades."""

    def __init__(self, database=None, broker=None):
        self.database = database
        self.broker = broker
        self._lock = threading.RLock()
        self.positions: dict[str, Any] = {}

    def recover(self) -> RecoveryReport:
        report = RecoveryReport()
        with self._lock:
            try:
                db = list(self.database.load_open_positions()) if self.database else []
                broker = list(self.broker.get_open_positions()) if self.broker else []
                report.database_positions = len(db)
                report.broker_positions = len(broker)
                broker_by_symbol = {}
                for p in broker:
                    symbol = getattr(p, "symbol", None) or p.get("symbol")
                    if symbol in broker_by_symbol:
                        report.duplicated_positions.append(symbol)
                    broker_by_symbol[symbol] = p
                db_symbols = set()
                for p in db:
                    symbol = getattr(p, "symbol", None) or p.get("symbol")
                    pid = getattr(p, "trade_id", None) or getattr(p, "position_id", None) or p.get("position_id", symbol)
                    db_symbols.add(symbol)
                    if symbol not in broker_by_symbol:
                        report.missing_on_broker.append(symbol)
                        continue
                    self.positions[str(pid)] = p
                    report.restored_positions += 1
                for symbol in broker_by_symbol:
                    if symbol not in db_symbols:
                        report.missing_in_database.append(symbol)
                report.success = not report.errors and not report.duplicated_positions
            except Exception as exc:
                logger.exception("Recovery failed")
                report.errors.append(str(exc))
            return report

    def get_positions(self):
        with self._lock:
            return dict(self.positions)

    def clear(self):
        with self._lock:
            self.positions.clear()
