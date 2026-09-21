"""Live-only startup sequence around Binance reconciliation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from core.binance_reconciliation import (
    AccountLocalPositionView,
    LocalPositionView,
    ReconciliationResult,
)
from core.binance_startup_reconciliation import BinanceStartupReconciliation
from core.execution_adapter import BinanceExecutionAdapter
from core.binance_protection import BinanceSpotProtection
from core.replica_position_state import ReplicaPositionStateStore
from core.startup_reconciliation_gate import StartupGateDecision, StartupReconciliationGate


@dataclass(frozen=True, slots=True)
class LiveStartupResult:
    decision: StartupGateDecision
    reconciliation: ReconciliationResult


class LiveStartupCoordinator:
    """Connect -> reconcile -> exact protection check -> gate."""

    def __init__(self, adapter: BinanceExecutionAdapter, tracked_symbols: Iterable[str]) -> None:
        self._adapter = adapter
        self._tracked_symbols = tuple(symbol.upper() for symbol in tracked_symbols)

    @staticmethod
    def _exact_protection_ok(snapshot) -> bool:
        """Require an active SELL stop with matching quantity and stop price."""
        for position in snapshot.local_positions:
            orders = snapshot.open_orders_by_symbol.get(position.symbol.upper(), ())
            matched = False
            for order in orders:
                if str(order.get("side", "")).upper() != "SELL":
                    continue
                if str(order.get("status", "")).upper() not in {"NEW", "PARTIALLY_FILLED", "PENDING_NEW"}:
                    continue
                if str(order.get("type", "")).upper() not in {"STOP_LOSS_LIMIT", "STOP_LOSS"}:
                    continue
                if abs(float(order.get("origQty", 0.0) or 0.0) - float(position.quantity)) > 1e-8:
                    continue
                if position.stop_price is not None:
                    stop = float(order.get("stopPrice", 0.0) or 0.0)
                    expected = float(position.stop_price)
                    if stop <= 0 or abs(stop - expected) > max(abs(expected) * 1e-8, 1e-12):
                        continue
                matched = True
                break
            if not matched:
                return False
        return True

    def start_account_replica(
        self,
        account_id: str,
        position_store: ReplicaPositionStateStore,
    ) -> LiveStartupResult:
        """Start one authenticated account from canonical replica state."""
        positions = tuple(
            AccountLocalPositionView(
                account_id=account_id,
                position_id=position.position_id,
                master_position_id=position.master_position_id,
                user_position_id=position.user_position_id,
                symbol=position.symbol,
                quantity=position.remaining_quantity,
                stop_price=position.stop_loss_price,
            )
            for position in position_store.active_for_connection(account_id)
        )
        self._adapter.connect()
        snapshot = BinanceStartupReconciliation(
            self._adapter,
            self._tracked_symbols,
        ).reconcile_account_replica(account_id, positions)
        if snapshot.result.safe_to_resume and not self._exact_account_protection_ok(snapshot):
            decision = StartupGateDecision(False, "RECONCILIATION_BLOCKED")
        else:
            decision = StartupReconciliationGate.evaluate(snapshot.result)
        return LiveStartupResult(decision=decision, reconciliation=snapshot.result)

    @staticmethod
    def _exact_account_protection_ok(snapshot) -> bool:
        """Require an active SELL stop for each account-local replica quantity."""
        for position in snapshot.local_positions:
            orders = snapshot.open_orders_by_symbol.get(position.symbol.upper(), ())
            matched = BinanceSpotProtection.has_active_sell_protection(
                list(orders),
                quantity=position.quantity,
                stop_price=position.stop_price,
            )
            if not matched:
                return False
        return True

    def start(self, local_positions: Iterable[LocalPositionView]) -> LiveStartupResult:
        local = tuple(local_positions)
        self._adapter.connect()
        snapshot = BinanceStartupReconciliation(self._adapter, self._tracked_symbols).reconcile(local)
        if snapshot.result.safe_to_resume and not self._exact_protection_ok(snapshot):
            decision = StartupGateDecision(False, "RECONCILIATION_BLOCKED")
        else:
            decision = StartupReconciliationGate.evaluate(snapshot.result)
        return LiveStartupResult(decision=decision, reconciliation=snapshot.result)
