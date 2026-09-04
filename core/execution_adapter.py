from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException

from core.execution_models import ExecutionRequest, ExecutionResult, OrderStatus, OrderType, OrderSide, OrderFees, SlippageInfo
from core.execution_exceptions import ExchangeConnectionError, ExchangeError, ExchangeRejectedOrderError


class ExecutionAdapter(ABC):
    def __init__(self, exchange_name: str) -> None:
        self._exchange_name = exchange_name

    @property
    def exchange_name(self) -> str:
        return self._exchange_name

    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def disconnect(self) -> None: ...

    @abstractmethod
    def is_connected(self) -> bool: ...

    @abstractmethod
    def execute(self, request: ExecutionRequest) -> ExecutionResult: ...

    @abstractmethod
    def cancel_order(self, symbol: str, order_id: str) -> bool: ...

    @abstractmethod
    def get_order(self, symbol: str, order_id: str) -> dict[str, Any]: ...


class BinanceExecutionAdapter(ExecutionAdapter):
    def __init__(self, api_key: str, api_secret: str, *, testnet: bool = False) -> None:
        super().__init__("BINANCE")
        self._api_key = api_key
        self._api_secret = api_secret
        self._testnet = testnet
        self._client: Client | None = None

    def connect(self) -> None:
        try:
            self._client = Client(self._api_key, self._api_secret, testnet=self._testnet)
            self._client.ping()
        except (BinanceAPIException, BinanceRequestException, Exception) as exc:
            raise ExchangeConnectionError(str(exc)) from exc

    def disconnect(self) -> None:
        self._client = None

    def is_connected(self) -> bool:
        if self._client is None:
            return False
        try:
            self._client.ping()
            return True
        except Exception:
            return False

    def _require_client(self) -> Client:
        if self._client is None:
            raise ExchangeConnectionError("Binance client is not connected.")
        return self._client

    @staticmethod
    def _safe_float(value: Any) -> float:
        if value in (None, ""):
            return 0.0
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def _convert_order_type(self, order_type: OrderType) -> str:
        mapping = {OrderType.MARKET: Client.ORDER_TYPE_MARKET, OrderType.LIMIT: Client.ORDER_TYPE_LIMIT}
        try:
            return mapping[order_type]
        except KeyError as exc:
            raise ExchangeError(f"Unsupported order type: {order_type}") from exc

    def _convert_side(self, side: OrderSide) -> str:
        return Client.SIDE_BUY if side == OrderSide.BUY else Client.SIDE_SELL

    def _convert_status(self, status: str) -> OrderStatus:
        mapping = {
            "NEW": OrderStatus.SUBMITTED,
            "PARTIALLY_FILLED": OrderStatus.PARTIALLY_FILLED,
            "FILLED": OrderStatus.FILLED,
            "CANCELED": OrderStatus.CANCELLED,
            "EXPIRED": OrderStatus.EXPIRED,
            "REJECTED": OrderStatus.REJECTED,
            "PENDING_CANCEL": OrderStatus.PENDING,
        }
        return mapping.get(status, OrderStatus.FAILED)

    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        client = self._require_client()
        params: dict[str, Any] = {"symbol": request.symbol, "side": self._convert_side(request.side), "type": self._convert_order_type(request.order_type)}
        if request.quantity > 0:
            params["quantity"] = request.quantity
        elif request.quote_quantity is not None:
            params["quoteOrderQty"] = request.quote_quantity
        if request.order_type == OrderType.LIMIT:
            params["price"] = request.price
            params["timeInForce"] = request.time_in_force.value
        if request.client_order_id:
            params["newClientOrderId"] = request.client_order_id
        try:
            raw = client.create_order(**params)
        except BinanceAPIException as exc:
            raise ExchangeRejectedOrderError(str(exc), request.request_id) from exc
        except BinanceRequestException as exc:
            raise ExchangeConnectionError(str(exc)) from exc
        except Exception as exc:
            raise ExchangeError(str(exc)) from exc
        executed_qty = self._safe_float(raw.get("executedQty"))
        avg_price = self._safe_float(raw.get("price"))
        if avg_price == 0.0:
            cumulative = self._safe_float(raw.get("cummulativeQuoteQty"))
            if cumulative > 0.0 and executed_qty > 0.0:
                avg_price = cumulative / executed_qty
        requested_price = request.price if request.price is not None else avg_price
        slippage = SlippageInfo(
            requested_price=requested_price, executed_price=avg_price,
            absolute_slippage=abs(avg_price - requested_price),
            percent_slippage=abs(avg_price - requested_price) / requested_price if requested_price > 0 else 0.0,
            accepted=True,
        )
        return ExecutionResult(
            request_id=request.request_id, client_order_id=request.client_order_id,
            exchange_order_id=str(raw.get("orderId", "")), symbol=request.symbol,
            side=request.side, order_type=request.order_type,
            status=self._convert_status(raw.get("status", "")), requested_price=request.price,
            requested_quantity=request.quantity, executed_price=avg_price,
            executed_quantity=executed_qty, remaining_quantity=max(0.0, request.quantity - executed_qty),
            average_price=avg_price, fees=OrderFees(), slippage=slippage,
            exchange=self.exchange_name, raw_response=raw,
        )

    def cancel_order(self, symbol: str, order_id: str) -> bool:
        client = self._require_client()
        try:
            client.cancel_order(symbol=symbol, orderId=order_id)
            return True
        except BinanceAPIException:
            return False
        except BinanceRequestException as exc:
            raise ExchangeConnectionError(str(exc)) from exc
        except Exception as exc:
            raise ExchangeError(str(exc)) from exc

    def get_order(self, symbol: str, order_id: str) -> dict[str, Any]:
        client = self._require_client()
        try:
            return client.get_order(symbol=symbol, orderId=order_id)
        except BinanceAPIException as exc:
            raise ExchangeRejectedOrderError(str(exc)) from exc
        except BinanceRequestException as exc:
            raise ExchangeConnectionError(str(exc)) from exc
        except Exception as exc:
            raise ExchangeError(str(exc)) from exc

    def get_account_snapshot(self) -> dict[str, Any]:
        """Return authenticated Spot account state without modifying it."""
        client = self._require_client()
        try:
            return client.get_account()
        except BinanceAPIException as exc:
            raise ExchangeError(str(exc)) from exc
        except BinanceRequestException as exc:
            raise ExchangeConnectionError(str(exc)) from exc
        except Exception as exc:
            raise ExchangeError(str(exc)) from exc

    def get_open_orders_snapshot(self, symbol: str) -> list[dict[str, Any]]:
        """Return active Spot orders for one symbol without modifying it."""
        client = self._require_client()
        try:
            return list(client.get_open_orders(symbol=symbol.upper()))
        except BinanceAPIException as exc:
            raise ExchangeError(str(exc)) from exc
        except BinanceRequestException as exc:
            raise ExchangeConnectionError(str(exc)) from exc
        except Exception as exc:
            raise ExchangeError(str(exc)) from exc
