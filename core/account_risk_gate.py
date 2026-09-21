"""Account-level safety gate for replicated trade instructions.

This gate protects the copy boundary itself. It does not replace Trade
Manager Part 6: once a replica is admitted here, the per-account Risk Gateway
remains authoritative for the account's full risk model.

The gate has no market-data or exchange dependency.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from core.account_registry import RegisteredAccount
from core.trade_replication import ReplicaInstruction, ReplicationAction


class AccountRiskDecision(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class AccountRiskReason(str, Enum):
    APPROVED = "APPROVED"
    ACCOUNT_NOT_ELIGIBLE = "ACCOUNT_NOT_ELIGIBLE"
    INVALID_ACCOUNT_EQUITY = "INVALID_ACCOUNT_EQUITY"
    INVALID_TARGET_VALUE = "INVALID_TARGET_VALUE"
    TARGET_EXCEEDS_AUTHORIZED_CAPITAL = "TARGET_EXCEEDS_AUTHORIZED_CAPITAL"
    INSUFFICIENT_FREE_BALANCE = "INSUFFICIENT_FREE_BALANCE"


@dataclass(frozen=True, slots=True)
class AccountExecutionSnapshot:
    """Current per-account financial state used only for copy safety."""

    account_equity: float
    free_balance: float
    estimated_fee: float = 0.0

    def __post_init__(self) -> None:
        if self.account_equity < 0.0:
            raise ValueError("account_equity must not be negative")
        if self.free_balance < 0.0:
            raise ValueError("free_balance must not be negative")
        if self.estimated_fee < 0.0:
            raise ValueError("estimated_fee must not be negative")


@dataclass(frozen=True, slots=True)
class AccountRiskResult:
    decision: AccountRiskDecision
    reason: AccountRiskReason
    target_quote_value: float
    available_after_fee: float
    metadata: dict[str, float | str]


class AccountExecutionSnapshotProvider(Protocol):
    """Provide live/paper financial state for one registered account."""

    def snapshot(self, account: RegisteredAccount) -> AccountExecutionSnapshot:
        ...


class AccountLevelRiskGate:
    """Enforce user-authorized capital and current-balance safety."""

    def evaluate(
        self,
        *,
        account: RegisteredAccount,
        instruction: ReplicaInstruction,
        snapshot: AccountExecutionSnapshot,
    ) -> AccountRiskResult:
        if not account.eligible_follower:
            return self._reject(
                AccountRiskReason.ACCOUNT_NOT_ELIGIBLE,
                instruction.target_quote_value,
                snapshot.free_balance,
            )

        if snapshot.account_equity <= 0.0:
            return self._reject(
                AccountRiskReason.INVALID_ACCOUNT_EQUITY,
                instruction.target_quote_value,
                snapshot.free_balance,
            )

        if instruction.action is not ReplicationAction.OPEN:
            return AccountRiskResult(
                AccountRiskDecision.APPROVED,
                AccountRiskReason.APPROVED,
                0.0,
                snapshot.free_balance,
                {
                    "account_equity": snapshot.account_equity,
                    "free_balance": snapshot.free_balance,
                    "authorized_capital": account.capital_basis,
                    "action": instruction.action.value,
                },
            )

        target = float(instruction.target_quote_value)
        if target <= 0.0:
            return self._reject(
                AccountRiskReason.INVALID_TARGET_VALUE,
                target,
                snapshot.free_balance,
            )

        if target > account.capital_basis + 1e-12:
            return self._reject(
                AccountRiskReason.TARGET_EXCEEDS_AUTHORIZED_CAPITAL,
                target,
                snapshot.free_balance,
                account_equity=snapshot.account_equity,
                authorized_capital=account.capital_basis,
            )

        available_after_fee = snapshot.free_balance - snapshot.estimated_fee
        if target > available_after_fee + 1e-12:
            return self._reject(
                AccountRiskReason.INSUFFICIENT_FREE_BALANCE,
                target,
                available_after_fee,
                account_equity=snapshot.account_equity,
                authorized_capital=account.capital_basis,
            )

        return AccountRiskResult(
            AccountRiskDecision.APPROVED,
            AccountRiskReason.APPROVED,
            target,
            available_after_fee,
            {
                "account_equity": snapshot.account_equity,
                "free_balance": snapshot.free_balance,
                "authorized_capital": account.capital_basis,
                "target_quote_value": target,
                "estimated_fee": snapshot.estimated_fee,
                "action": instruction.action.value,
            },
        )

    @staticmethod
    def _reject(
        reason: AccountRiskReason,
        target: float,
        available: float,
        *,
        account_equity: float = 0.0,
        authorized_capital: float = 0.0,
    ) -> AccountRiskResult:
        return AccountRiskResult(
            AccountRiskDecision.REJECTED,
            reason,
            target,
            available,
            {
                "account_equity": account_equity,
                "available_after_fee": available,
                "authorized_capital": authorized_capital,
            },
        )


__all__ = [
    "AccountExecutionSnapshot",
    "AccountExecutionSnapshotProvider",
    "AccountLevelRiskGate",
    "AccountRiskDecision",
    "AccountRiskReason",
    "AccountRiskResult",
]
