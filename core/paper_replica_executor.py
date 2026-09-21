"""Paper-only executor for account-scoped replica instructions.

This integration harness proves that one shared trade intent can be executed
against multiple independent PaperExecutionAdapter accounts using the price
already captured in the shared instruction. It performs no market-data fetches
and makes no network calls.

It is intentionally not a Live execution implementation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from core.execution_models import (
    ExecutionContext,
    ExecutionRequest,
    ExecutionResult,
    ExecutionSource,
    OrderSide,
    OrderType,
)
from core.paper_execution_adapter import PaperExecutionAdapter
from core.replica_position_state import ReplicaPositionRecord, ReplicaPositionStateStore
from core.trade_replication import ReplicaInstruction, ReplicationAction


@dataclass(slots=True)
class PaperReplicaExecution:
    connection_id: str
    result: ExecutionResult


class PaperReplicaExecutor:
    """Execute OPEN replica instructions against independent Paper accounts."""

    def __init__(
        self,
        adapters: Mapping[str, PaperExecutionAdapter],
        *,
        position_store: ReplicaPositionStateStore | None = None,
    ) -> None:
        self._adapters = dict(adapters)
        self.position_store = position_store
        self.executions: list[PaperReplicaExecution] = []

    def execute(self, instruction: ReplicaInstruction) -> bool:
        adapter = self._adapters.get(instruction.connection_id)
        if adapter is None:
            return False

        if instruction.action is ReplicationAction.OPEN:
            return self._execute_open(instruction, adapter)

        if instruction.action is ReplicationAction.CLOSE:
            return self._execute_close(instruction, adapter)

        return False

    def _execute_open(
        self,
        instruction: ReplicaInstruction,
        adapter: PaperExecutionAdapter,
    ) -> bool:
        price = instruction.reference_entry_price
        if price is None or price <= 0.0 or instruction.target_quote_value <= 0.0:
            return False

        quantity = instruction.target_quote_value / price
        client_order_id = (
            f"REPL-{instruction.intent_id[:12]}-"
            f"{instruction.connection_id[:12]}"
        )
        request = ExecutionRequest(
            symbol=instruction.symbol,
            side=instruction.side,
            order_type=OrderType.MARKET,
            price=price,
            stop_price=instruction.stop_loss_price,
            quantity=quantity,
            client_order_id=client_order_id,
            context=ExecutionContext(
                exchange_name=adapter.exchange_name,
                source=ExecutionSource.PAPER,
                metadata={
                    **dict(instruction.metadata or {}),
                    "replication_connection_id": instruction.connection_id,
                    "replication_intent_id": instruction.intent_id,
                    "replication_action": instruction.action.value,
                    "trade_mode": instruction.trade_mode,
                    "stop_loss_price": instruction.stop_loss_price,
                },
            ),
        )

        result = self._execute_request(instruction, adapter, request)
        if not result.is_success:
            return False

        if self.position_store is not None:
            position_id = (
                f"RPOS-{instruction.intent_id}-"
                f"{instruction.connection_id}"
            )
            existing = self.position_store.get(position_id)
            if existing is None:
                self.position_store.register(
                    ReplicaPositionRecord(
                        position_id=position_id,
                        connection_id=instruction.connection_id,
                        source_intent_id=instruction.intent_id,
                        symbol=instruction.symbol,
                        quantity=result.executed_quantity,
                        remaining_quantity=result.executed_quantity,
                        entry_price=result.average_price,
                        stop_loss_price=instruction.stop_loss_price,
                    )
                )
            elif (
                existing.connection_id != instruction.connection_id
                or existing.source_intent_id != instruction.intent_id
                or existing.symbol.upper() != instruction.symbol.upper()
                or abs(existing.quantity - result.executed_quantity) > 1e-12
            ):
                return False
        return True

    def _execute_close(
        self,
        instruction: ReplicaInstruction,
        adapter: PaperExecutionAdapter,
    ) -> bool:
        if self.position_store is None:
            return False
        source_open_intent_id = str(instruction.source_open_intent_id).strip()
        price = instruction.reference_exit_price
        if not source_open_intent_id or price is None or price <= 0.0:
            return False

        position = self.position_store.active_for_account(
            connection_id=instruction.connection_id,
            source_intent_id=source_open_intent_id,
        )
        if position is None:
            return False

        quantity = position.close_quantity(instruction.close_fraction)
        if quantity <= 0.0:
            return False

        request = ExecutionRequest(
            symbol=position.symbol,
            side=instruction.side,
            order_type=OrderType.MARKET,
            price=price,
            quantity=quantity,
            client_order_id=(
                f"REPL-CLOSE-{instruction.intent_id[:12]}-"
                f"{instruction.connection_id[:12]}"
            ),
            context=ExecutionContext(
                exchange_name=adapter.exchange_name,
                source=ExecutionSource.PAPER,
                metadata={
                    **dict(instruction.metadata or {}),
                    "replication_connection_id": instruction.connection_id,
                    "replication_intent_id": instruction.intent_id,
                    "replication_action": instruction.action.value,
                    "source_open_intent_id": source_open_intent_id,
                    "replica_position_id": position.position_id,
                    "trade_mode": instruction.trade_mode,
                },
            ),
        )

        result = self._execute_request(instruction, adapter, request)
        if not result.is_success:
            return False

        self.position_store.apply_close(
            position_id=position.position_id,
            executed_quantity=result.executed_quantity,
        )
        return True

    def _execute_request(
        self,
        instruction: ReplicaInstruction,
        adapter: PaperExecutionAdapter,
        request: ExecutionRequest,
    ) -> ExecutionResult:
        if not adapter.is_connected():
            adapter.connect()

        result = adapter.execute(request)
        self.executions.append(
            PaperReplicaExecution(
                connection_id=instruction.connection_id,
                result=result,
            )
        )
        return result


__all__ = [
    "PaperReplicaExecution",
    "PaperReplicaExecutor",
]
