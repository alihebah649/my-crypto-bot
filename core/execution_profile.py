"""Execution profile metadata for multi-account future deployments.

This module is intentionally non-executing. It gives the runtime a stable,
typed way to distinguish Paper, a user's Binance Spot account, and a Binance
Spot Copy-Trading Lead portfolio without storing API credentials here.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AccountScope(str, Enum):
    PAPER = "PAPER"
    USER_SPOT = "USER_SPOT"
    BINANCE_LEAD_SPOT = "BINANCE_LEAD_SPOT"


@dataclass(frozen=True, slots=True)
class ExecutionProfile:
    """Stable execution/account identity carried with an execution runtime."""

    profile_id: str
    exchange: str
    account_scope: AccountScope
    account_ref: str = ""
    live_enabled: bool = False

    def __post_init__(self) -> None:
        if not str(self.profile_id).strip():
            raise ValueError("profile_id must not be empty")
        if not str(self.exchange).strip():
            raise ValueError("exchange must not be empty")
        if self.live_enabled and self.account_scope is AccountScope.PAPER:
            raise ValueError("Paper execution profile cannot enable live execution")

    @property
    def is_paper(self) -> bool:
        return self.account_scope is AccountScope.PAPER

    @property
    def is_binance_lead(self) -> bool:
        return self.account_scope is AccountScope.BINANCE_LEAD_SPOT

    def to_metadata(self) -> dict[str, str | bool]:
        return {
            "execution_profile_id": self.profile_id,
            "exchange": self.exchange.upper(),
            "account_scope": self.account_scope.value,
            "account_ref": self.account_ref,
            "live_enabled": self.live_enabled,
        }

    @classmethod
    def paper(cls) -> "ExecutionProfile":
        return cls(
            profile_id="paper-default",
            exchange="PAPER",
            account_scope=AccountScope.PAPER,
            live_enabled=False,
        )
