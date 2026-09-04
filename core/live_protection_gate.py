"""Safety gate for exchange-side protection integration.

This module is intentionally policy-only: it never submits an order. It
ensures callers cannot treat a filled live BUY as protected before the
exchange-side protection has been positively confirmed.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ProtectionState(str, Enum):
    UNPROTECTED = "UNPROTECTED"
    PROTECTING = "PROTECTING"
    PROTECTED = "PROTECTED"
    EXIT_TRIGGERED = "EXIT_TRIGGERED"
    EXIT_FILLED = "EXIT_FILLED"
    RECONCILING = "RECONCILING"
    ORPHAN_POSITION = "ORPHAN_POSITION"


@dataclass(frozen=True, slots=True)
class ProtectionGateResult:
    allowed: bool
    state: ProtectionState
    reason: str


def evaluate_protection_gate(
    *,
    live_mode: bool,
    buy_filled: bool,
    protection_confirmed: bool,
) -> ProtectionGateResult:
    """Return whether a filled BUY may be treated as protected.

    Paper mode always remains outside this gate. In live mode, a filled BUY is
    not considered safe until the exchange confirms active protection.
    """
    if not live_mode:
        return ProtectionGateResult(True, ProtectionState.PROTECTED, "PAPER_MODE_NO_LIVE_PROTECTION_REQUIRED")
    if not buy_filled:
        return ProtectionGateResult(False, ProtectionState.UNPROTECTED, "BUY_NOT_FILLED")
    if not protection_confirmed:
        return ProtectionGateResult(False, ProtectionState.PROTECTING, "EXCHANGE_PROTECTION_NOT_CONFIRMED")
    return ProtectionGateResult(True, ProtectionState.PROTECTED, "EXCHANGE_PROTECTION_CONFIRMED")
