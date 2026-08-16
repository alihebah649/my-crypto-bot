"""Trade Manager Part 5 recovery/reconciliation primitives.

Recovery is observational first: it compares database, in-memory and broker
state and reports discrepancies. It does not silently repair or invent state.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List

@dataclass(slots=True)
class RecoveryRecord:
    symbol: str
    database_position: Any = None
    memory_position: Any = None
    broker_position: Any = None
    broker_oco: Any = None
    notes: List[str] = field(default_factory=list)

class RecoveryComparisonMatrix:
    def __init__(self, database, memory, broker, oco_scanner):
        self.database = database
        self.memory = memory
        self.broker = broker
        self.oco_scanner = oco_scanner

    def build(self) -> Dict[str, RecoveryRecord]:
        matrix: Dict[str, RecoveryRecord] = {}
        for position in self.database.load_open_positions() or []:
            matrix.setdefault(position.symbol, RecoveryRecord(position.symbol)).database_position = position
        for position in self.memory.get_open_positions() if hasattr(self.memory, "get_open_positions") else self.memory.get_all_positions():
            matrix.setdefault(position.symbol, RecoveryRecord(position.symbol)).memory_position = position
        for position in self.broker.get_open_positions() or []:
            matrix.setdefault(position.symbol, RecoveryRecord(position.symbol)).broker_position = position
        for oco in (self.oco_scanner.load_open_oco_orders() or {}).values():
            matrix.setdefault(oco.symbol, RecoveryRecord(oco.symbol)).broker_oco = oco
        return matrix

    @staticmethod
    def discrepancies(matrix: Dict[str, RecoveryRecord]) -> Dict[str, RecoveryRecord]:
        return {
            symbol: row for symbol, row in matrix.items()
            if not (row.database_position and row.memory_position and row.broker_position)
        }

@dataclass(slots=True)
class RecoveryReport:
    database_positions: int = 0
    broker_positions: int = 0
    restored_positions: int = 0
    missing_on_broker: List[str] = field(default_factory=list)
    missing_in_database: List[str] = field(default_factory=list)
    duplicated_positions: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    success: bool = False

class RecoveryManager:
    """Rebuilds in-memory visibility only; it never opens or closes broker trades."""
    def __init__(self, database, broker):
        self.database = database
        self.broker = broker
        self.positions: Dict[str, Any] = {}

    def recover(self) -> RecoveryReport:
        report = RecoveryReport()
        try:
            db_positions = list(self.database.load_open_positions() or [])
            broker_positions = list(self.broker.get_open_positions() or [])
            report.database_positions = len(db_positions)
            report.broker_positions = len(broker_positions)
            broker_by_symbol = {p.symbol: p for p in broker_positions}
            db_symbols = set()
            for position in db_positions:
                db_symbols.add(position.symbol)
                if position.symbol not in broker_by_symbol:
                    report.missing_on_broker.append(position.symbol)
                    continue
                self.positions[position.position_id] = position
                report.restored_positions += 1
            for position in broker_positions:
                if position.symbol not in db_symbols:
                    report.missing_in_database.append(position.symbol)
            report.success = not report.errors
        except Exception as exc:
            report.errors.append(str(exc))
            report.success = False
        return report

    def get_positions(self) -> Dict[str, Any]:
        return dict(self.positions)

    def clear(self) -> None:
        self.positions.clear()
