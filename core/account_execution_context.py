"""Per-account execution context for replication boundaries.

The context is a small, immutable snapshot assembled before a replica is
admitted to execution. It composes account identity/profile with the settlement
entry permission without taking ownership of position lifecycle.

Settlement can block OPEN actions only. CLOSE actions remain executable so an
overdue account is never liquidated by the billing boundary.
"""
from __future__ import annotations

from dataclasses import dataclass

from core.account_connection import AccountConnection
from core.account_registry import RegisteredAccount
from core.settlement_trading_policy import SettlementTradingPolicy
from core.trade_replication import ReplicationAction


@dataclass(frozen=True, slots=True)
class AccountExecutionContext:
    """Account-scoped execution boundary assembled from current metadata."""

    connection: AccountConnection
    capital_basis: float
    copy_enabled: bool
    settlement: SettlementTradingPolicy

    @classmethod
    def from_account(cls, account: RegisteredAccount) -> "AccountExecutionContext":
        return cls(
            connection=account.connection,
            capital_basis=float(account.capital_basis),
            copy_enabled=bool(account.copy_enabled),
            settlement=account.settlement_policy,
        )

    @property
    def account_id(self) -> str:
        return self.connection.connection_id

    @property
    def execution_profile(self):
        return self.connection.profile

    @property
    def allow_new_entries(self) -> bool:
        return self.copy_enabled and self.settlement.allow_new_entries

    @property
    def manage_existing_positions(self) -> bool:
        return self.settlement.manage_existing_positions

    @property
    def force_close_existing_positions(self) -> bool:
        return self.settlement.force_close_existing_positions

    def allows_replication_action(self, action: ReplicationAction) -> bool:
        """Return whether this boundary permits the requested lifecycle action."""
        if action is ReplicationAction.OPEN:
            return self.allow_new_entries

        # CLOSE is never blocked by settlement. Normal trading/risk layers
        # remain responsible for deciding whether/how the existing position
        # should be closed.
        return True

    def metadata(self) -> dict[str, str | bool | float]:
        return {
            "account_id": self.account_id,
            "execution_profile_id": self.connection.profile.profile_id,
            "account_scope": self.connection.profile.account_scope.value,
            "connection_state": self.connection.state.value,
            "copy_enabled": self.copy_enabled,
            "capital_basis": self.capital_basis,
            **self.settlement.metadata(),
        }


__all__ = ["AccountExecutionContext"]
