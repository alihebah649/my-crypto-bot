"""Paper-only executor for account-scoped replica instructions.

Uses the single replica position state contract and the shared market price
captured in the instruction. No per-user market-data polling or live exchange
calls are performed.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from core.execution_models import (
    ExecutionContext,
    ExecutionRequest,
    ExecutionResult,
    ExecutionSource,
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
    """Execute replica instructions against independent Paper accounts."""

    def __init__(
        self,
        adapters: Mapping[str, PaperExecutionAdapter],
        position_store: ReplicaPositionStateStore | None = None,
    ) -> None:
        self._adapters = dict(adapters)
        self.position_store = position_store or ReplicaPositionStateStore()
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

        master_position_id = instruction.master_position_id or instruction.intent_id
        idempotency_key = ReplicaPositionRecord.make_idempotency_key(
            instruction.intent_id,
            instruction.connection_id,
            "OPEN",
        )
        prior = self.position_store.get_by_idempotency_key(idempotency_key)
        if prior is not None:
            return True

        existing = self.position_store.by_master_position(
            master_position_id,
            instruction.connection_id,
        )
        if existing:
            # A reused master_position_id with a different open intent is a
            # lifecycle identity conflict, not a safe retry.
            return False

        quantity = instruction.target_quote_value / price
        request = ExecutionRequest(
            symbol=instruction.symbol,
            side=instruction.side,
            order_type=OrderType.MARKET,
            price=price,
            stop_price=instruction.stop_loss_price,
            quantity=quantity,
            client_order_id=(
                f"REPL-{instruction.intent_id[:12]}-"
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
                    "master_position_id": master_position_id,
                    "trade_mode": instruction.trade_mode,
                    "stop_loss_price": instruction.stop_loss_price,
                },
            ),
        )

        result = self._execute_request(instruction.connection_id, adapter, result_request=request)
        if not result.is_success:
            return False

        position_id = f"RPOS-{master_position_id}-{instruction.connection_id}"
        self.position_store.register(
            ReplicaPositionRecord(
                position_id=position_id,
                connection_id=instruction.connection_id,
                source_intent_id=instruction.intent_id,
                symbol=instruction.symbol,
                quantity=result.executed_quantity,
                remaining_quantity=result.executed_quantity,
                entry_price=result.average_price or result.executed_price,
                stop_loss_price=instruction.stop_loss_price,
                master_position_id=master_position_id,
                user_position_id=position_id,
                idempotency_key=idempotency_key,
                client_order_id=result.client_order_id,
                exchange_order_id=result.exchange_order_id,
            )
        )
        return True

    def _execute_close(
        self,
        instruction: ReplicaInstruction,
        adapter: PaperExecutionAdapter,
    ) -> bool:
        master_position_id = instruction.master_position_id or instruction.intent_id
        if self.position_store.close_applied_for_master_position(
            connection_id=instruction.connection_id,
            master_position_id=master_position_id,
            close_intent_id=instruction.intent_id,
        ):
            return True

        position = self.position_store.active_for_master_position(
            connection_id=instruction.connection_id,
            master_position_id=master_position_id,
        )
        price = instruction.reference_close_price
        if position is None or price is None or price <= 0.0:
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
            reduce_only=True,
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
                    "master_position_id": master_position_id,
                    "replica_position_id": position.user_position_id,
                },
            ),
        )

        result = self._execute_request(instruction.connection_id, adapter, result_request=request)
        if not result.is_success:
            return False

        self.position_store.apply_close(
            position_id=position.position_id,
            executed_quantity=result.executed_quantity,
            close_intent_id=instruction.intent_id,
            master_close_position_id=master_position_id,
            exchange_order_id=result.exchange_order_id,
        )
        return True

    def _execute_request(
        self,
        connection_id: str,
        adapter: PaperExecutionAdapter,
        *,
        result_request: ExecutionRequest,
    ) -> ExecutionResult:
        if not adapter.is_connected():
            adapter.connect()

        result = adapter.execute(result_request)
        self.executions.append(
            PaperReplicaExecution(
                connection_id=connection_id,
                result=result,
            )
        )
        return result


__all__ = [
    "PaperReplicaExecution",
    "PaperReplicaExecutor",
]
