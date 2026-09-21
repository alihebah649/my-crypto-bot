"""Deterministic reconciliation primitives for Binance Spot positions."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True, slots=True)
class ExchangeAsset:
    symbol: str
    quantity: float


@dataclass(frozen=True, slots=True)
class LocalPositionView:
    symbol: str
    quantity: float
    position_id: str = ""
    stop_price: float | None = None


@dataclass(frozen=True, slots=True)
class AccountLocalPositionView:
    """Identity-aware local position for one specific account/replica."""

    account_id: str
    position_id: str
    master_position_id: str
    user_position_id: str
    symbol: str
    quantity: float
    stop_price: float | None = None

    def __post_init__(self) -> None:
        for name in (
            "account_id",
            "position_id",
            "master_position_id",
            "user_position_id",
            "symbol",
        ):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} must not be empty")
        if float(self.quantity) <= 0.0:
            raise ValueError("quantity must be positive")


@dataclass(frozen=True, slots=True)
class ReconciliationIssue:
    code: str
    symbol: str
    detail: str
    account_id: str = ""
    position_id: str = ""


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


def reconcile_account_spot_positions(
    account_id: str,
    exchange_assets: Iterable[ExchangeAsset],
    local_positions: Iterable[AccountLocalPositionView],
    active_protection_by_position_id: dict[str, bool],
    *,
    dust_tolerance: float = 1e-12,
    quantity_tolerance: float = 1e-8,
) -> ReconciliationResult:
    """Reconcile one exchange account against identity-aware replica state.

    Binance Spot exposes an account-level asset balance, not a position ID.
    Therefore the exchange quantity is compared with the sum of local active
    quantities for each symbol. Multiple simultaneous local positions for one
    symbol are rejected because the exchange balance cannot safely attribute
    quantity to individual replica identities.
    """
    scoped_account = str(account_id).strip()
    if not scoped_account:
        raise ValueError("account_id must not be empty")

    exchange: dict[str, float] = {}
    for asset in exchange_assets:
        symbol = asset.symbol.upper()
        exchange[symbol] = exchange.get(symbol, 0.0) + max(0.0, float(asset.quantity))

    local = tuple(local_positions)
    issues: list[ReconciliationIssue] = []
    local_by_symbol: dict[str, list[AccountLocalPositionView]] = {}

    for position in local:
        if position.account_id != scoped_account:
            issues.append(
                ReconciliationIssue(
                    "ACCOUNT_SCOPE_MISMATCH",
                    position.symbol.upper(),
                    (
                        f"position account_id={position.account_id!r} does not match "
                        f"reconciliation account_id={scoped_account!r}"
                    ),
                    account_id=scoped_account,
                    position_id=position.position_id,
                )
            )
            continue
        local_by_symbol.setdefault(position.symbol.upper(), []).append(position)

    for symbol, quantity in exchange.items():
        if quantity <= dust_tolerance:
            continue
        positions = local_by_symbol.get(symbol, [])
        if not positions:
            issues.append(
                ReconciliationIssue(
                    "ORPHAN_POSITION",
                    symbol,
                    f"account={scoped_account} exchange quantity={quantity} has no local active replica position",
                    account_id=scoped_account,
                )
            )

    for symbol, positions in local_by_symbol.items():
        exchange_qty = exchange.get(symbol, 0.0)
        if len(positions) > 1:
            issues.append(
                ReconciliationIssue(
                    "MULTIPLE_LOCAL_POSITIONS_SAME_SYMBOL",
                    symbol,
                    (
                        f"account={scoped_account} has {len(positions)} active local "
                        "positions for one Spot symbol; exchange balance cannot "
                        "attribute quantity safely by position identity"
                    ),
                    account_id=scoped_account,
                )
            )

        expected_qty = sum(float(position.quantity) for position in positions)
        if exchange_qty <= dust_tolerance:
            issues.append(
                ReconciliationIssue(
                    "LOCAL_POSITION_MISSING_ON_EXCHANGE",
                    symbol,
                    (
                        f"account={scoped_account} local quantity={expected_qty} "
                        "but exchange quantity is absent"
                    ),
                    account_id=scoped_account,
                )
            )
        elif abs(exchange_qty - expected_qty) > quantity_tolerance:
            issues.append(
                ReconciliationIssue(
                    "EXCHANGE_QUANTITY_MISMATCH",
                    symbol,
                    (
                        f"account={scoped_account} local aggregate quantity={expected_qty} "
                        f"but exchange quantity={exchange_qty}"
                    ),
                    account_id=scoped_account,
                )
            )

        for position in positions:
            if not active_protection_by_position_id.get(position.user_position_id, False):
                issues.append(
                    ReconciliationIssue(
                        "UNPROTECTED_POSITION",
                        symbol,
                        (
                            f"account={scoped_account} replica position "
                            f"{position.position_id} has no confirmed exchange-side protection"
                        ),
                        account_id=scoped_account,
                        position_id=position.position_id,
                    )
                )

    return ReconciliationResult(
        safe_to_resume=not issues,
        issues=tuple(issues),
    )


def reconcile_spot_positions(
    exchange_assets: Iterable[ExchangeAsset],
    local_positions: Iterable[LocalPositionView],
    active_protection_by_symbol: dict[str, bool],
    *,
    dust_tolerance: float = 1e-12,
    quantity_tolerance: float = 1e-8,
) -> ReconciliationResult:
    """Compare exchange-owned assets with local active positions.

    Non-dust exchange assets must have a local position. Local positions must
    exist on the exchange, have matching quantity within tolerance, and have
    confirmed exchange-side protection.
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

        if abs(exchange_qty - float(position.quantity)) > quantity_tolerance:
            issues.append(ReconciliationIssue(
                "EXCHANGE_QUANTITY_MISMATCH",
                symbol,
                f"local quantity={position.quantity} but exchange quantity={exchange_qty}",
            ))

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
