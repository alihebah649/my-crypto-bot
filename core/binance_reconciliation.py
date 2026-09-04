"""Deterministic reconciliation primitives for Binance Spot positions.

This module deliberately does not trade, modify Strategy, or modify Trade Manager.
It compares exchange balances/open orders with local positions and returns an
explicit decision for the application lifecycle to act on.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True, slots=True)
class ExchangeAsset:
    symbol: str
    quantity: float


@dataclass(frozen=True, slots=True)
class LocalPositionView:
    symbol: str
    quantity: float
    position_id: str = ""


@dataclass(frozen=True, slots=True)
class ReconciliationIssue:
    code: str
    symbol: str
    detail: str


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    safe_to_resume: bool
    issues: tuple[ReconciliationIssue, ...]

    @property
    def has_orphans(self) -> bool:
        return any(i.code == "ORPHAN_POSITION" for i in self.issues)

    @property
    def has_unprotected(self) -> bool:
        return any(i.code == "UNPROTECTED_POSITION" for i in self.issues)


def reconcile_spot_positions(
    exchange_assets: Iterable[ExchangeAsset],
    local_positions: Iterable[LocalPositionView],
    active_protection_by_symbol: dict[str, bool],
    *,
    dust_tolerance: float = 1e-12,
) -> ReconciliationResult:
    """Compare exchange-owned assets with local active positions.

    Only non-dust assets are considered.  A locally known active position must
    have exchange-side protection confirmed.  An exchange asset with no local
    position is an ORPHAN_POSITION and blocks new entries until explicitly
    reconciled by the application.
    """
    exchange: dict[str, float] = {}
    for asset in exchange_assets:
        symbol = asset.symbol.upper()
        exchange[symbol] = exchange.get(symbol, 0.0) + max(0.0, float(asset.quantity))

    local: dict[str, LocalPositionView] = {}
    for position in local_positions:
        symbol = position.symbol.upper()
        local[symbol] = position

    issues: list[ReconciliationIssue] = []

    for symbol, quantity in exchange.items():
        if quantity <= dust_tolerance:
            continue
        if symbol not in local:
            issues.append(ReconciliationIssue(
                "ORPHAN_POSITION",
                symbol,
                f"exchange quantity={quantity} has no local active position",
            ))

    for symbol, position in local.items():
        exchange_qty = exchange.get(symbol, 0.0)
        if exchange_qty <= dust_tolerance:
            issues.append(ReconciliationIssue(
                "LOCAL_POSITION_MISSING_ON_EXCHANGE",
                symbol,
                f"local quantity={position.quantity} but exchange quantity is absent",
            ))
            continue
        if not active_protection_by_symbol.get(symbol, False):
            issues.append(ReconciliationIssue(
                "UNPROTECTED_POSITION",
                symbol,
                "local position exists but exchange-side protection is not confirmed",
            ))

    return ReconciliationResult(
        safe_to_resume=not issues,
        issues=tuple(issues),
    )
