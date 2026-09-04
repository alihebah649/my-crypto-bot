"""Live-only startup sequence around Binance reconciliation.

The coordinator is deliberately separate from Paper Trading and Trade Manager.
It connects Binance, performs read-only reconciliation, then fails closed unless
local positions, exchange balances, and exact exchange-side stop protection agree.
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

    @staticmethod
    def _exact_protection_ok(adapter, positions: tuple[LocalPositionView, ...]) -> bool:
        """Require exact quantity and stop match for every local position."""
        for position in positions:
            orders = adapter.get_open_orders_snapshot(position.symbol)
            matched = False
            for order in orders:
                if str(order.get("side", "")).upper() != "SELL":
                    continue
                if str(order.get("status", "")).upper() not in {"NEW", "PARTIALLY_FILLED", "PENDING_NEW"}:
                    continue
                if str(order.get("type", "")).upper() not in {"STOP_LOSS_LIMIT", "STOP_LOSS"}:
                    continue
                quantity = float(order.get("origQty", 0.0) or 0.0)
                if abs(quantity - float(position.quantity)) > 1e-8:
                    continue
                if position.stop_price is not None:
                    stop = float(order.get("stopPrice", 0.0) or 0.0)
                    if stop <= 0 or abs(stop - float(position.stop_price)) > max(abs(float(position.stop_price)) * 1e-8, 1e-12):
                        continue
                matched = True
                break
            if not matched:
                return False
        return True

    def start(self, local_positions: Iterable[LocalPositionView]) -> LiveStartupResult:
        local = tuple(local_positions)
        self._adapter.connect()
        reconciler = BinanceStartupReconciliation(self._adapter, self._tracked_symbols)
        snapshot = reconciler.reconcile(local)
        result = snapshot.result
        if result.safe_to_resume and not self._exact_protection_ok(self._adapter, local):
            decision = StartupGateDecision(False, "RECONCILIATION_BLOCKED")
        else:
            decision = StartupReconciliationGate.evaluate(result)
        return LiveStartupResult(decision=decision, reconciliation=result)
