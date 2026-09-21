"""Application-level registry for accounts participating in shared trade replication.

The registry contains account metadata only. It never fetches market data,
resolves credentials, or executes exchange orders.

One shared trading decision can therefore be fanned out to all eligible
followers without running Strategy/Brain once per account.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from core.account_connection import AccountConnection, ConnectionState
from core.settlement_trading_policy import SettlementState, SettlementTradingPolicy
from core.trade_replication import FollowerAccount


class AccountRole(str, Enum):
    MASTER = "MASTER"
    FOLLOWER = "FOLLOWER"


@dataclass(frozen=True, slots=True)
class RegisteredAccount:
    """Account metadata used by the application-level orchestration layer."""

    connection: AccountConnection
    role: AccountRole
    capital_basis: float
    copy_enabled: bool = True
    settlement_policy: SettlementTradingPolicy = SettlementTradingPolicy(SettlementState.CURRENT)

    def __post_init__(self) -> None:
        if self.capital_basis <= 0.0:
            raise ValueError("capital_basis must be positive")

    @property
    def eligible_follower(self) -> bool:
        return (
            self.role is AccountRole.FOLLOWER
            and self.copy_enabled
            and self.connection.state is ConnectionState.READY
            and not self.connection.profile.is_paper
        )

    def as_follower(self) -> FollowerAccount | None:
        if not self.eligible_follower:
            return None
        return FollowerAccount(
            connection_id=self.connection.connection_id,
            capital_basis=self.capital_basis,
            enabled=True,
        )


class AccountRegistry:
    """In-memory source of truth for accounts participating in orchestration.

    Persistence belongs to the application data layer later. Keeping this
    object in-memory prevents accidental coupling to exchange polling or
    credential storage.
    """

    def __init__(self) -> None:
        self._accounts: dict[str, RegisteredAccount] = {}

    def register(self, account: RegisteredAccount) -> None:
        connection_id = account.connection.connection_id
        if connection_id in self._accounts:
            raise ValueError(f"account already registered: {connection_id}")
        self._accounts[connection_id] = account

    def replace(self, account: RegisteredAccount) -> None:
        self._accounts[account.connection.connection_id] = account

    def remove(self, connection_id: str) -> RegisteredAccount:
        try:
            return self._accounts.pop(connection_id)
        except KeyError as exc:
            raise KeyError(f"account not registered: {connection_id}") from exc

    def get(self, connection_id: str) -> RegisteredAccount | None:
        return self._accounts.get(connection_id)

    def all(self) -> tuple[RegisteredAccount, ...]:
        return tuple(self._accounts.values())

    def followers(self) -> tuple[FollowerAccount, ...]:
        result: list[FollowerAccount] = []
        for account in self._accounts.values():
            follower = account.as_follower()
            if follower is not None:
                result.append(follower)
        return tuple(result)

    def count(self) -> int:
        return len(self._accounts)


__all__ = [
    "AccountRegistry",
    "AccountRole",
    "RegisteredAccount",
]
