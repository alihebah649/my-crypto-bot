"""Safe paper-trading execution adapter for Shadow Trading Bot."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
import tempfile
from typing import Any, Optional
from uuid import uuid4

from core.execution_adapter import ExecutionAdapter
from core.execution_models import (
    ExecutionRequest,
    ExecutionResult,
    ExecutionSource,
    OrderFees,
    OrderSide,
    OrderStatus,
    RejectReason,
    SlippageInfo,
)
from core.models import TradeType


@dataclass(slots=True)
class PaperBalance:
    cash: float
    reserved: float = 0.0
    assets: dict[str, float] = field(default_factory=dict)


class PaperExecutionAdapter(ExecutionAdapter):
    """Exchange-free execution adapter used only for paper trading.

    ``state_path`` persists cash, owned assets and market prices so a restart
    cannot silently recreate an empty paper account. Orders are intentionally
    not restored because paper orders are filled/rejected synchronously and
    there are no pending exchange orders to reconstruct.
    """

    def __init__(self, initial_cash: float = 1000.0, fee_rate: float = 0.001,
                 state_path: Optional[str] = None) -> None:
        super().__init__("PAPER")
        if initial_cash < 0:
            raise ValueError("initial_cash must be non-negative")
        if fee_rate < 0:
            raise ValueError("fee_rate must be non-negative")
        self.fee_rate = float(fee_rate)
        self.balance = PaperBalance(cash=float(initial_cash))
        self.orders: dict[str, ExecutionResult] = {}
        self.market_prices: dict[str, float] = {}
        self.state_path = state_path
        self._connected = False
        if self.state_path:
            self._load_state()

    def connect(self) -> None:
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    def set_market_price(self, symbol: str, price: float) -> None:
        price = float(price)
        if price <= 0:
            raise ValueError("market price must be positive")
        self.market_prices[symbol.upper()] = price
        self._persist_state()

    def get_market_price(self, symbol: str) -> float:
        try:
            return self.market_prices[symbol.upper()]
        except KeyError as exc:
            raise ValueError(f"No paper market price for {symbol}") from exc

    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        symbol = request.symbol.upper()
        price = request.price if request.price is not None else self.get_market_price(symbol)
        quantity = float(request.quantity)

        if quantity <= 0:
            return self._rejected(request, RejectReason.INVALID_QUANTITY)
        if price <= 0:
            return self._rejected(request, RejectReason.INVALID_PRICE)

        gross = price * quantity
        fee = gross * self.fee_rate

        if request.side == OrderSide.BUY:
            total_cost = gross + fee
            if total_cost > self.balance.cash + 1e-12:
                return self._rejected(request, RejectReason.INSUFFICIENT_BALANCE)
            self.balance.cash -= total_cost
            self.balance.assets[symbol] = self.balance.assets.get(symbol, 0.0) + quantity
        elif request.side == OrderSide.SELL:
            held = self.balance.assets.get(symbol, 0.0)
            if quantity > held + 1e-12:
                return self._rejected(request, RejectReason.INSUFFICIENT_BALANCE)
            self.balance.assets[symbol] = max(0.0, held - quantity)
            self.balance.cash += gross - fee
        else:
            return self._rejected(request, RejectReason.UNKNOWN)

        now = datetime.now(timezone.utc)
        trade_type = request.context.metadata.get("trade_type", TradeType.SCALPING_SWING.value)
        order_id = f"PAPER-{uuid4().hex[:16]}"
        result = ExecutionResult(
            request_id=request.request_id,
            client_order_id=request.client_order_id,
            exchange_order_id=order_id,
            symbol=symbol,
            side=request.side,
            order_type=request.order_type,
            status=OrderStatus.FILLED,
            requested_price=price,
            requested_quantity=quantity,
            executed_price=price,
            executed_quantity=quantity,
            remaining_quantity=0.0,
            average_price=price,
            fees=OrderFees(exchange_fee=fee),
            slippage=SlippageInfo(requested_price=price, executed_price=price),
            message=f"Paper execution: {trade_type}",
            created_at=now,
            submitted_at=now,
            completed_at=now,
            exchange=self.exchange_name,
            raw_response={"source": ExecutionSource.PAPER.value, "trade_type": trade_type},
        )
        self.orders[order_id] = result
        self._persist_state()
        return result

    def cancel_order(self, symbol: str, order_id: str) -> bool:
        result = self.orders.get(order_id)
        if result is None or result.symbol != symbol.upper():
            return False
        return result.status in (OrderStatus.CREATED, OrderStatus.PENDING, OrderStatus.SUBMITTED)

    def get_order(self, symbol: str, order_id: str) -> dict[str, Any]:
        result = self.orders.get(order_id)
        if result is None or result.symbol != symbol.upper():
            return {}
        return {
            "orderId": result.exchange_order_id,
            "clientOrderId": result.client_order_id,
            "symbol": result.symbol,
            "side": result.side.value,
            "status": result.status.value,
            "price": result.executed_price,
            "executedQty": result.executed_quantity,
            "source": ExecutionSource.PAPER.value,
        }

    def _rejected(self, request: ExecutionRequest, reason: RejectReason) -> ExecutionResult:
        now = datetime.now(timezone.utc)
        result = ExecutionResult(
            request_id=request.request_id,
            client_order_id=request.client_order_id,
            symbol=request.symbol.upper(),
            side=request.side,
            order_type=request.order_type,
            status=OrderStatus.REJECTED,
            requested_price=request.price,
            requested_quantity=request.quantity,
            reject_reason=reason,
            message=f"Paper order rejected: {reason.value}",
            created_at=now,
            completed_at=now,
            exchange=self.exchange_name,
            raw_response={"source": ExecutionSource.PAPER.value},
        )
        self.orders[f"REJECTED-{uuid4().hex[:16]}"] = result
        self._persist_state()
        return result

    def snapshot(self) -> dict[str, Any]:
        return {
            "source": ExecutionSource.PAPER.value,
            "cash": self.balance.cash,
            "reserved": self.balance.reserved,
            "assets": dict(self.balance.assets),
            "orders": len(self.orders),
            "fee_rate": self.fee_rate,
            "market_prices": dict(self.market_prices),
        }

    def _persist_state(self) -> None:
        if not self.state_path:
            return
        directory = os.path.dirname(os.path.abspath(self.state_path))
        os.makedirs(directory, exist_ok=True)
        payload = {
            "version": 1,
            "cash": self.balance.cash,
            "reserved": self.balance.reserved,
            "assets": self.balance.assets,
            "market_prices": self.market_prices,
            "fee_rate": self.fee_rate,
        }
        fd, temp_path = tempfile.mkstemp(prefix="paper-state-", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self.state_path)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    def _load_state(self) -> None:
        if not os.path.exists(self.state_path):
            return
        try:
            with open(self.state_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            if payload.get("version") != 1:
                raise ValueError("unsupported paper state version")
            if payload.get("fee_rate") is not None and abs(float(payload["fee_rate"]) - self.fee_rate) > 1e-12:
                raise ValueError("persisted fee_rate differs from configured fee_rate")
            self.balance = PaperBalance(
                cash=float(payload["cash"]),
                reserved=float(payload.get("reserved", 0.0)),
                assets={str(k): float(v) for k, v in payload.get("assets", {}).items()},
            )
            self.market_prices = {str(k): float(v) for k, v in payload.get("market_prices", {}).items()}
        except Exception as exc:
            raise RuntimeError(f"Unable to restore PaperExecutionAdapter: {exc}") from exc
