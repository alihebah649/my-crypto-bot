"""Binance Spot-side protection primitives.

This module is deliberately isolated from strategy and Trade Manager.  It does
not decide *when* a position should exit; it only places/cancels the exchange-
side protective SELL OCO and reads back open orders so a higher-level runtime
can reconcile state after restart or market-data outages.

The caller must inject an already authenticated Binance client.  Paper trading
must never instantiate this class with the live trading client.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class BinanceProtectionClient(Protocol):
    def create_oco_order(self, **kwargs: Any) -> dict[str, Any]: ...
    def get_open_orders(self, *, symbol: str) -> list[dict[str, Any]]: ...
    def cancel_order(self, *, symbol: str, orderId: Any) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class ProtectionRequest:
    symbol: str
    quantity: float
    take_profit_price: float
    stop_price: float
    stop_limit_price: float

    def validate(self) -> None:
        if not self.symbol:
            raise ValueError("symbol is required")
        if self.quantity <= 0:
            raise ValueError("quantity must be positive")
        if self.take_profit_price <= 0 or self.stop_price <= 0 or self.stop_limit_price <= 0:
            raise ValueError("protection prices must be positive")
        if not self.stop_limit_price < self.stop_price:
            raise ValueError("stop_limit_price must be below stop_price for a SELL protection order")
        if not self.take_profit_price > self.stop_price:
            raise ValueError("take_profit_price must be above stop_price for a SELL protection order")


class BinanceSpotProtection:
    """Small, deterministic wrapper around Binance Spot OCO protection."""

    def __init__(self, client: BinanceProtectionClient) -> None:
        self._client = client

    def place_sell_protection(self, request: ProtectionRequest) -> dict[str, Any]:
        request.validate()
        return self._client.create_oco_order(
            symbol=request.symbol.upper(),
            side="SELL",
            quantity=request.quantity,
            price=str(request.take_profit_price),
            stopPrice=str(request.stop_price),
            stopLimitPrice=str(request.stop_limit_price),
            stopLimitTimeInForce="GTC",
        )

    def open_protection_orders(self, symbol: str) -> list[dict[str, Any]]:
        return list(self._client.get_open_orders(symbol=symbol.upper()))

    def cancel_order(self, symbol: str, order_id: Any) -> dict[str, Any]:
        return self._client.cancel_order(symbol=symbol.upper(), orderId=order_id)

    @staticmethod
    def has_active_sell_protection(
        orders: list[dict[str, Any]],
        *,
        quantity: float | None = None,
        stop_price: float | None = None,
        quantity_tolerance: float = 1e-8,
        price_tolerance: float | None = None,
    ) -> bool:
        """Confirm a live SELL stop protection matching the expected position.

        When quantity/stop_price are supplied, the matching order must carry
        the same quantity and stop price within tolerance.  A TP-only order or
        unrelated SELL order is not sufficient protection.
        """
        active = {"NEW", "PARTIALLY_FILLED", "PENDING_NEW"}
        stop_types = {"STOP_LOSS_LIMIT", "STOP_LOSS"}
        for order in orders:
            if str(order.get("side", "")).upper() != "SELL":
                continue
            if str(order.get("status", "")).upper() not in active:
                continue
            order_type = str(order.get("type", "")).upper()
            if stop_price is not None:
                if order_type not in stop_types:
                    continue
            elif order_type not in stop_types | {"TAKE_PROFIT_LIMIT", "TAKE_PROFIT"}:
                continue

            if quantity is not None:
                candidate_qty = float(order.get("origQty", 0.0) or 0.0)
                if abs(candidate_qty - quantity) > quantity_tolerance:
                    continue

            if stop_price is not None:
                candidate_stop = float(order.get("stopPrice", 0.0) or 0.0)
                tolerance = max(abs(stop_price) * 1e-8, 1e-12) if price_tolerance is None else price_tolerance
                if candidate_stop <= 0 or abs(candidate_stop - stop_price) > tolerance:
                    continue

            return True
        return False
