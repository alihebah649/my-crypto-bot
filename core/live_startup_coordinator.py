"""Live-only startup sequence around Binance reconciliation.

This coordinator intentionally does not restore persistence itself and does not
change Paper Trading. The caller supplies the already-restored local positions.
It connects the Binance execution adapter, performs read-only reconciliation,
and fails closed when reconciliation is not safe.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from core.binance_reconciliation import LocalPositionView, ReconciliationResult
from core.binance_startup_reconciliation import BinanceStartupReconciliation
from core.execution_adapter import BinanceExecutionAdapter
from core.startup_reconciliation_gate import StartupGateDecision, StartupReconciliationGate


@dataclass(frozen=True, slots=True)
class LiveStartupResult:
    decision: StartupGateDecision
    reconciliation: ReconciliationResult


class LiveStartupCoordinator:
    """Connect -> reconcile -> gate. No market scanning occurs on failure."""

    def __init__(self, adapter: BinanceExecutionAdapter, tracked_symbols: Iterable[str]) -> None:
        self._adapter = adapter
        self._tracked_symbols = tuple(symbol.upper() for symbol in tracked_symbols)

    def start(self, local_positions: Iterable[LocalPositionView]) -> LiveStartupResult:
        self._adapter.connect()
        reconciler = BinanceStartupReconciliation(self._adapter, self._tracked_symbols)
        snapshot = reconciler.reconcile(local_positions)
        decision = StartupReconciliationGate.evaluate(snapshot.result)
        return LiveStartupResult(decision=decision, reconciliation=snapshot.result)
