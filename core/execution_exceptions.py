from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# ==========================================================
# Base Exception
# ==========================================================

@dataclass(slots=True)
class ExecutionError(Exception):
    """
    Base class لجميع أخطاء Execution Layer.
    """

    message: str
    code: str = "EXECUTION_ERROR"
    request_id: Optional[str] = None

    def __str__(self) -> str:
        if self.request_id:
            return (
                f"[{self.code}] "
                f"{self.message} "
                f"(request={self.request_id})"
            )

        return f"[{self.code}] {self.message}"


# ==========================================================
# Validation
# ==========================================================

class ValidationError(ExecutionError):

    def __init__(
        self,
        message: str,
        request_id: Optional[str] = None,
    ):
        super().__init__(
            message=message,
            code="VALIDATION_ERROR",
            request_id=request_id,
        )


class InvalidSymbolError(ValidationError):

    def __init__(
        self,
        symbol: str,
        request_id: Optional[str] = None,
    ):
        super().__init__(
            f"Invalid symbol: {symbol}",
            request_id,
        )


class InvalidPriceError(ValidationError):

    def __init__(
        self,
        price: float,
        request_id: Optional[str] = None,
    ):
        super().__init__(
            f"Invalid price: {price}",
            request_id,
        )


class InvalidQuantityError(ValidationError):

    def __init__(
        self,
        quantity: float,
        request_id: Optional[str] = None,
    ):
        super().__init__(
            f"Invalid quantity: {quantity}",
            request_id,
        )


# ==========================================================
# Risk
# ==========================================================

class RiskRejectedError(ExecutionError):

    def __init__(
        self,
        reason: str,
        request_id: Optional[str] = None,
    ):
        super().__init__(
            message=reason,
            code="RISK_REJECTED",
            request_id=request_id,
        )


class InsufficientBalanceError(ExecutionError):

    def __init__(
        self,
        asset: str,
        required: float,
        available: float,
        request_id: Optional[str] = None,
    ):
        super().__init__(
            message=(
                f"Insufficient balance "
                f"{asset}: "
                f"required={required}, "
                f"available={available}"
            ),
            code="INSUFFICIENT_BALANCE",
            request_id=request_id,
        )


# ==========================================================
# Exchange Errors
# ==========================================================

class ExchangeError(ExecutionError):

    def __init__(
        self,
        message: str = "Exchange error",
        request_id: Optional[str] = None,
    ):
        super().__init__(
            message=message,
            code="EXCHANGE_ERROR",
            request_id=request_id,
        )


class ExchangeConnectionError(ExchangeError):

    def __init__(
        self,
        message: str = "Unable to connect to exchange",
        request_id: Optional[str] = None,
    ):
        super().__init__(
            message=message,
            request_id=request_id,
        )
        self.code = "EXCHANGE_CONNECTION_ERROR"


class ExchangeResponseError(ExchangeError):

    def __init__(
        self,
        message: str = "Invalid exchange response",
        request_id: Optional[str] = None,
    ):
        super().__init__(
            message=message,
            request_id=request_id,
        )
        self.code = "EXCHANGE_RESPONSE_ERROR"


class ExchangeRejectedOrderError(ExchangeError):

    def __init__(
        self,
        reason: str,
        request_id: Optional[str] = None,
    ):
        super().__init__(
            message=f"Exchange rejected order: {reason}",
            request_id=request_id,
        )
        self.code = "EXCHANGE_REJECTED_ORDER"


# ==========================================================
# Timeout
# ==========================================================

class TimeoutError(ExecutionError):

    def __init__(
        self,
        timeout: float,
        request_id: Optional[str] = None,
    ):
        super().__init__(
            message=f"Execution timeout after {timeout:.2f}s",
            code="TIMEOUT",
            request_id=request_id,
        )


# ==========================================================
# Network
# ==========================================================

class NetworkError(ExecutionError):

    def __init__(
        self,
        message: str = "Network error",
        request_id: Optional[str] = None,
    ):
        super().__init__(
            message=message,
            code="NETWORK_ERROR",
            request_id=request_id,
        )


class RateLimitError(NetworkError):

    def __init__(
        self,
        retry_after: float = 0.0,
        request_id: Optional[str] = None,
    ):
        msg = "Rate limit exceeded"

        if retry_after > 0:
            msg += f" (retry after {retry_after:.2f}s)"

        super().__init__(
            message=msg,
            request_id=request_id,
        )

        self.code = "RATE_LIMIT"


# ==========================================================
# Slippage
# ==========================================================

class SlippageExceededError(ExecutionError):

    def __init__(
        self,
        expected: float,
        actual: float,
        request_id: Optional[str] = None,
    ):
        super().__init__(
            message=(
                f"Slippage exceeded "
                f"(expected={expected:.6f}, "
                f"actual={actual:.6f})"
            ),
            code="SLIPPAGE_EXCEEDED",
            request_id=request_id,
        )


# ==========================================================
# Retry
# ==========================================================

class RetryLimitExceededError(ExecutionError):

    def __init__(
        self,
        retries: int,
        request_id: Optional[str] = None,
    ):
        super().__init__(
            message=f"Retry limit exceeded ({retries})",
            code="RETRY_LIMIT_EXCEEDED",
            request_id=request_id,
        )


# ==========================================================
# Duplicate Orders
# ==========================================================

class DuplicateOrderError(ExecutionError):

    def __init__(
        self,
        client_order_id: str,
        request_id: Optional[str] = None,
    ):
        super().__init__(
            message=(
                f"Duplicate client order id: "
                f"{client_order_id}"
            ),
            code="DUPLICATE_ORDER",
            request_id=request_id,
        )


# ==========================================================
# Position
# ==========================================================

class PositionError(ExecutionError):
    pass


class PositionNotFoundError(PositionError):

    def __init__(
        self,
        symbol: str,
        request_id: Optional[str] = None,
    ):
        super().__init__(
            message=f"Position not found: {symbol}",
            code="POSITION_NOT_FOUND",
            request_id=request_id,
        )


class PositionAlreadyExistsError(PositionError):

    def __init__(
        self,
        symbol: str,
        request_id: Optional[str] = None,
    ):
        super().__init__(
            message=f"Position already exists: {symbol}",
            code="POSITION_ALREADY_EXISTS",
            request_id=request_id,
        )


# ==========================================================
# Order State
# ==========================================================

class OrderStateError(ExecutionError):

    def __init__(
        self,
        message: str,
        request_id: Optional[str] = None,
    ):
        super().__init__(
            message=message,
            code="ORDER_STATE_ERROR",
            request_id=request_id,
        )


# ==========================================================
# Factory Helper
# ==========================================================

_EXCEPTION_MAP: dict[str, type[ExecutionError]] = {
    "VALIDATION_ERROR": ValidationError,
    "EXCHANGE_ERROR": ExchangeError,
    "NETWORK_ERROR": NetworkError,
    "TIMEOUT": TimeoutError,
    "INSUFFICIENT_BALANCE": InsufficientBalanceError,
    "SLIPPAGE_EXCEEDED": SlippageExceededError,
    "RISK_REJECTED": RiskRejectedError,
}


def exception_from_code(
    code: str,
    message: str,
    request_id: Optional[str] = None,
) -> ExecutionError:
    """
    إنشاء Exception مناسب انطلاقًا من Error Code.
    """

    cls = _EXCEPTION_MAP.get(
        code,
        ExecutionError,
    )

    if cls is ExecutionError:
        return cls(
            message=message,
            code=code,
            request_id=request_id,
        )

    return cls(message, request_id)  # type: ignore[arg-type]
