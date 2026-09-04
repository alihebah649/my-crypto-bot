"""Read-only Binance Spot startup reconciliation runtime."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Protocol

from core.binance_protection import BinanceSpotProtection
from core.binance_reconciliation import ExchangeAsset, LocalPositionView, ReconciliationResult, reconcile_spot_positions


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
    """Collect exchange state and run the existing deterministic reconciliation."""

    def __init__(self, client: BinanceReconciliationClient) -> None:
        self._client = client

    @staticmethod
    def _account_assets(account: dict[str, Any], symbols: Iterable[str]) -> tuple[ExchangeAsset, ...]:
        """Map only base assets represented by the bot's tracked USDT symbols."""
        tracked = {symbol.upper() for symbol in symbols}
        assets_by_base: dict[str, str] = {}
        for symbol in tracked:
            if symbol.endswith("USDT"):
                assets_by_base[symbol[:-4]] = symbol
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
        symbols = {p.symbol.upper() for p in local}
        account = self._client.get_account()
        assets = self._account_assets(account, symbols)
        orders_by_symbol = {
            symbol: list(self._client.get_open_orders(symbol=symbol))
            for symbol in symbols
        }
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
