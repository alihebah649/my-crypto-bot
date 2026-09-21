"""Settlement state boundary for follower trading.

A payment/settlement issue may block NEW entries, but it must never force-close
or alter existing positions. Position management remains owned by the trading
engine and its safety layers.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SettlementState(str, Enum):
    CURRENT = "CURRENT"
    SETTLEMENT_REQUIRED = "SETTLEMENT_REQUIRED"
    DISABLED = "DISABLED"


@dataclass(frozen=True, slots=True)
class SettlementTradingPolicy:
    """Translate settlement state into an entry permission only."""

    state: SettlementState

    @property
    def allow_new_entries(self) -> bool:
        return self.state is SettlementState.CURRENT

    @property
    def manage_existing_positions(self) -> bool:
        # Settlement status never owns position lifecycle.
        return True

    @property
    def force_close_existing_positions(self) -> bool:
        # Deliberately always false: no payment-driven liquidation.
        return False

    def metadata(self) -> dict[str, str | bool]:
        return {
            "settlement_state": self.state.value,
            "allow_new_entries": self.allow_new_entries,
            "manage_existing_positions": self.manage_existing_positions,
            "force_close_existing_positions": self.force_close_existing_positions,
        }


__all__ = ["SettlementState", "SettlementTradingPolicy"]
