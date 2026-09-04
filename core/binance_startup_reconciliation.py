"""Read-only Binance Spot startup reconciliation runtime.

This module is the application boundary between Binance account state and the
pure reconciliation rules. It never places, cancels, or modifies orders.

A caller may use the returned result as a startup gate: only a successful
reconciliation should permit new entries to resume.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, Iterable

from core.binance_protection import BinanceSpotProtection
from core.binance_reconciliation import (
    ExchangeAsset,
    LocalPositionView,
    ReconciliationResult,
    reconcile_spot_positions,
)


class BinanceReconciliationClient(Protocol):
    def get_account(self) -> dict[str, Any]: ...
    def get_open_orders(self, *, symbol: str) -> list[dict[str, Any]]: ...


@dataclass(frozen=True, slots=True)
class StartupReconciliationSnapshot:
    exchange_assets: tuple[ExchangeAsset, ...]
    local_positions: tuple[LocalPositionView, ...]
    active_protection_by_symbol: dict[str, bool]
    result: ReconciliationResult


class BinanceStartupReconciliation:
    """Collect Binance state and run the existing deterministic reconciliation."""

    def __init__(self, client: BinanceReconciliationClient) -> None:
        self._client = client

    @staticmethod
    def _account_assets(account: dict[str, Any]) -> tuple[ExchangeAsset, ...]:
        assets: list[ExchangeAsset] = []
        for row in account.get("balances", []) or []:
            asset = str(row.get("asset", "")).upper()
            free = float(row.get("free", 0.0) or 0.0)
            locked = float(row.get("locked", 0.0) or 0.0)
            quantity = max(0.0, free + locked)
            if asset and quantity > 0.0:
                assets.append(ExchangeAsset(symbol=f"{asset}USDT", quantity=quantity))
        return tuple(assets)

    @staticmethod
    def _active_orders(client: BinanceReconciliationClient, symbols: Iterable[str]) -> dict[str, list[dict[str, Any]]]:
        return {
            symbol.upper(): list(client.get_open_orders(symbol=symbol.upper()))
            for symbol in symbols
        }

    def reconcile(
        self,
        local_positions: Iterable[LocalPositionView],
    ) -> StartupReconciliationSnapshot:
        local = tuple(local_positions)
        account = self._client.get_account()
        assets = self._account_assets(account)
        symbols = {p.symbol.upper() for p in local}
        orders_by_symbol = self._active_orders(self._client, symbols)
        protection = {
            symbol: BinanceSpotProtection.has_active_sell_protection(
                orders_by_symbol.get(symbol, []),
                quantity=next((p.quantity for p in local if p.symbol.upper() == symbol), None),
            )
            for symbol in symbols
        }
        result = reconcile_spot_positions(assets, local, protection)
        return StartupReconciliationSnapshot(
            exchange_assets=assets,
            local_positions=local,
            active_protection_by_symbol=protection,
            result=result,
        )
