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
from core.trade_replication import ReplicaInstruction, ReplicationAction
from core.replica_position import ReplicaPosition
from core.replica_position_repository import ReplicaPositionRepository
from trade_manager.models import PositionStatus
import time


@dataclass(slots=True)
class PaperReplicaExecution:
    connection_id: str
    result: ExecutionResult


class PaperReplicaExecutor:
    """Execute OPEN replica instructions against independent Paper accounts."""

    def __init__(
        self,
        adapters: Mapping[str, PaperExecutionAdapter],
        position_repository: ReplicaPositionRepository | None = None,
    ) -> None:
        self._adapters = dict(adapters)
        self.position_repository = position_repository or ReplicaPositionRepository()
        self.executions: list[PaperReplicaExecution] = []

    def execute(self, instruction: ReplicaInstruction) -> bool:
        adapter = self._adapters.get(instruction.connection_id)
        if adapter is None:
            return False

        if instruction.action is ReplicationAction.CLOSE:
            return self._execute_close(instruction, adapter)

        master_position_id = instruction.master_position_id or instruction.intent_id
        existing = self.position_repository.get_by_master_position(master_position_id, instruction.connection_id)
        if any(p.status is not PositionStatus.CLOSED for p in existing):
            return False

        price = instruction.reference_entry_price
        if price is None or price <= 0.0 or instruction.target_quote_value <= 0.0:
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
                    "trade_mode": instruction.trade_mode,
                    "stop_loss_price": instruction.stop_loss_price,
                },
            ),
        )

        if not adapter.is_connected():
            adapter.connect()

        result = adapter.execute(request)
        if result.is_success:
            position = ReplicaPosition.from_open(
                account_id=instruction.connection_id,
                master_intent_id=instruction.intent_id,
                master_position_id=instruction.master_position_id or instruction.intent_id,
                symbol=instruction.symbol,
                quantity=result.executed_quantity,
                entry_price=result.average_price or result.executed_price,
                stop_loss=instruction.stop_loss_price,
                client_order_id=result.client_order_id,
                exchange_order_id=result.exchange_order_id,
                metadata={"trade_mode": instruction.trade_mode},
            )
            self.position_repository.upsert(position)
        self.executions.append(
            PaperReplicaExecution(
                connection_id=instruction.connection_id,
                result=result,
            )
        )
        return result.is_success


__all__ = [
    "PaperReplicaExecution",
    "PaperReplicaExecutor",
]
