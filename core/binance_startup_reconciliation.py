"""Read-only Binance Spot startup reconciliation runtime."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Protocol

from core.binance_protection import BinanceSpotProtection
from core.binance_reconciliation import (
    ExchangeAsset,
    LocalPositionView,
    ReconciliationResult,
    reconcile_spot_positions,
)


class BinanceReconciliationClient(Protocol):
    def get_account_snapshot(self) -> dict[str, Any]: ...
    def get_open_orders_snapshot(self, symbol: str) -> list[dict[str, Any]]: ...


@dataclass(frozen=True, slots=True)
class StartupReconciliationSnapshot:
    exchange_assets: tuple[ExchangeAsset, ...]
    local_positions: tuple[LocalPositionView, ...]
    open_orders_by_symbol: dict[str, tuple[dict[str, Any], ...]]
    active_protection_by_symbol: dict[str, bool]
    result: ReconciliationResult


class BinanceStartupReconciliation:
    """Collect exchange state once and run deterministic reconciliation."""

    def __init__(self, client: BinanceReconciliationClient, tracked_symbols: Iterable[str]) -> None:
        self._client = client
        self._tracked_symbols = tuple(symbol.upper() for symbol in tracked_symbols)

    @staticmethod
    def _account_assets(account: dict[str, Any], symbols: Iterable[str]) -> tuple[ExchangeAsset, ...]:
        """Map only configured Spot base assets; ignore USDT and unrelated assets."""
        tracked = {symbol.upper() for symbol in symbols}
        assets_by_base = {
            symbol[:-4]: symbol
            for symbol in tracked
            if symbol.endswith("USDT")
        }
        assets: list[ExchangeAsset] = []
        for row in account.get("balances", []) or []:
            asset = str(row.get("asset", "")).upper()
            symbol = assets_by_base.get(asset)
            if not symbol:
                continue
            free = float(row.get("free", 0.0) or 0.0)
            locked = float(row.get("locked", 0.0) or 0.0)
            quantity = max(0.0, free + locked)
            if quantity > 0.0:
                assets.append(ExchangeAsset(symbol=symbol, quantity=quantity))
        return tuple(assets)

    def reconcile(self, local_positions: Iterable[LocalPositionView]) -> StartupReconciliationSnapshot:
        local = tuple(local_positions)
        tracked = set(self._tracked_symbols)
        local_symbols = {p.symbol.upper() for p in local}
        symbols = tracked | local_symbols

        account = self._client.get_account_snapshot()
        assets = self._account_assets(account, symbols)
        orders_by_symbol = {
            symbol: tuple(self._client.get_open_orders_snapshot(symbol))
            for symbol in local_symbols
        }
        protection = {
            symbol: BinanceSpotProtection.has_active_sell_protection(
                orders_by_symbol.get(symbol, ()),
                quantity=next((p.quantity for p in local if p.symbol.upper() == symbol), None),
                stop_price=next((p.stop_price for p in local if p.symbol.upper() == symbol), None),
            )
            for symbol in local_symbols
        }
        result = reconcile_spot_positions(assets, local, protection)
        return StartupReconciliationSnapshot(
            exchange_assets=assets,
            local_positions=local,
            open_orders_by_symbol=orders_by_symbol,
            active_protection_by_symbol=protection,
            result=result,
        )
