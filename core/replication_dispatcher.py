"""Orchestration-only dispatcher for shared trade-intent replication.

The dispatcher coordinates:
    MasterTradeIntent -> AccountRegistry -> Account-Level Copy Risk
    -> ReplicationPlanner -> DeliveryLedger -> Executor

It intentionally knows nothing about indicators, market-data fetching,
credentials, or exchange-specific APIs. A separate executor callback receives
each approved ReplicaInstruction.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from core.account_registry import AccountRegistry
from core.account_risk_gate import (
    AccountExecutionSnapshotProvider,
    AccountLevelRiskGate,
    AccountRiskDecision,
)
from core.replication_delivery import (
    DeliveryState,
    ReplicationDeliveryLedger,
)
from core.trade_replication import (
    MasterTradeIntent,
    ReplicaInstruction,
    TradeReplicationPlanner,
)


class ReplicationDispatchError(RuntimeError):
    """Raised when dispatch orchestration cannot construct a delivery."""


@dataclass(frozen=True, slots=True)
class DispatchResult:
    intent_id: str
    planned: int
    dispatched: int
    skipped_duplicates: int
    failed: int
    instructions: tuple[ReplicaInstruction, ...]
    risk_rejected: int = 0


ReplicaExecutor = Callable[[ReplicaInstruction], bool]


class TradeReplicationDispatcher:
    """Fan-out one canonical intent to eligible accounts."""

    def __init__(
        self,
        registry: AccountRegistry,
        *,
        ledger: ReplicationDeliveryLedger | None = None,
        risk_gate: AccountLevelRiskGate | None = None,
        account_state_provider: AccountExecutionSnapshotProvider | None = None,
    ) -> None:
        if (risk_gate is None) != (account_state_provider is None):
            raise ValueError(
                "risk_gate and account_state_provider must be supplied together"
            )

        self.registry = registry
        self.ledger = ledger or ReplicationDeliveryLedger()
        self.risk_gate = risk_gate
        self.account_state_provider = account_state_provider

    def dispatch(
        self,
        intent: MasterTradeIntent,
        executor: ReplicaExecutor,
    ) -> DispatchResult:
        planned = TradeReplicationPlanner.plan(
            intent,
            self.registry.followers(),
        )

        dispatched = 0
        skipped_duplicates = 0
        failed = 0
        risk_rejected = 0
        executable: list[ReplicaInstruction] = []

        for instruction in planned:
            if self.risk_gate is not None:
                account = self.registry.get(instruction.connection_id)
                if account is None:
                    risk_rejected += 1
                    continue

                assert self.account_state_provider is not None
                snapshot = self.account_state_provider.snapshot(account)
                risk_result = self.risk_gate.evaluate(
                    account=account,
                    instruction=instruction,
                    snapshot=snapshot,
                )
                if risk_result.decision is AccountRiskDecision.REJECTED:
                    risk_rejected += 1
                    continue

            record = self.ledger.register_new(
                intent_id=instruction.intent_id,
                connection_id=instruction.connection_id,
                action=instruction.action.value,
            )

            # COMPLETED and DISPATCHED deliveries are not replayed
            # automatically. A DISPATCHED record may represent an in-flight
            # exchange operation after a crash, so replaying it could duplicate
            # an order. FAILED deliveries are explicitly retryable.
            if record.state is DeliveryState.FAILED:
                record = self.ledger.transition(
                    record.delivery_key,
                    DeliveryState.NEW,
                )
            elif record.state is not DeliveryState.NEW:
                skipped_duplicates += 1
                continue

            executable.append(instruction)

            self.ledger.transition(
                record.delivery_key,
                DeliveryState.DISPATCHED,
            )

            try:
                success = bool(executor(instruction))
            except Exception:
                self.ledger.transition(
                    record.delivery_key,
                    DeliveryState.FAILED,
                )
                failed += 1
                continue

            if success:
                self.ledger.transition(
                    record.delivery_key,
                    DeliveryState.COMPLETED,
                )
                dispatched += 1
            else:
                self.ledger.transition(
                    record.delivery_key,
                    DeliveryState.FAILED,
                )
                failed += 1

        return DispatchResult(
            intent_id=intent.intent_id,
            planned=len(planned),
            dispatched=dispatched,
            skipped_duplicates=skipped_duplicates,
            failed=failed,
            instructions=tuple(executable),
            risk_rejected=risk_rejected,
        )


__all__ = [
    "DispatchResult",
    "ReplicationDispatchError",
    "TradeReplicationDispatcher",
]
