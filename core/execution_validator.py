from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from core.execution_models import (
    ExecutionRequest,
    OrderType,
)

from core.execution_exceptions import (
    ValidationError,
    InvalidPriceError,
    InvalidQuantityError,
    InvalidSymbolError,
)


# ==========================================================
# Validation Report
# ==========================================================

@dataclass(slots=True)
class ValidationReport:
    """
    نتيجة عملية التحقق.

    لا ترمي الاستثناءات مباشرة، بل تجمع جميع الأخطاء
    ليقرر Execution Engine كيف يتعامل معها.
    """

    valid: bool = True

    errors: list[str] = field(default_factory=list)

    warnings: list[str] = field(default_factory=list)

    def add_error(self, message: str) -> None:
        self.valid = False
        self.errors.append(message)

    def add_warning(self, message: str) -> None:
        self.warnings.append(message)

    @property
    def has_errors(self) -> bool:
        return len(self.errors) > 0

    @property
    def has_warnings(self) -> bool:
        return len(self.warnings) > 0


# ==========================================================
# Execution Validator
# ==========================================================

class ExecutionValidator:
    """
    مسؤول عن التحقق من صحة طلب التنفيذ
    قبل دخوله إلى Execution Engine.
    """

    def __init__(
        self,
        *,
        max_quantity: float = 1_000_000,
        max_price: float = 10_000_000,
        min_price: float = 0.0,
        max_slippage: float = 0.05,
        allow_empty_client_id: bool = True,
    ):

        self.max_quantity = max_quantity

        self.max_price = max_price

        self.min_price = min_price

        self.max_slippage = max_slippage

        self.allow_empty_client_id = allow_empty_client_id

    # ======================================================
    # Public API
    # ======================================================

    def validate(
        self,
        request: ExecutionRequest,
    ) -> ValidationReport:

        report = ValidationReport()

        self._validate_symbol(request, report)

        self._validate_quantity(request, report)

        self._validate_price(request, report)

        self._validate_stop_price(request, report)

        self._validate_slippage(request, report)

        self._validate_timeout(request, report)

        self._validate_client_order_id(request, report)

        return report

    def validate_or_raise(
        self,
        request: ExecutionRequest,
    ) -> None:

        report = self.validate(request)

        if report.valid:
            return

        raise ValidationError(
            "; ".join(report.errors),
            request.request_id,
        )

    # ======================================================
    # Symbol
    # ======================================================

    def _validate_symbol(
        self,
        request: ExecutionRequest,
        report: ValidationReport,
    ) -> None:

        symbol = request.symbol.strip()

        if not symbol:
            report.add_error("Symbol is empty.")
            return

        if len(symbol) < 4:
            report.add_error(
                "Symbol length is invalid."
            )
            return

        if " " in symbol:
            report.add_error(
                "Symbol contains spaces."
            )

        if symbol != symbol.upper():
            report.add_warning(
                "Symbol should be uppercase."
            )

    # ======================================================
    # Quantity
    # ======================================================

    def _validate_quantity(
        self,
        request: ExecutionRequest,
        report: ValidationReport,
    ) -> None:

        qty = request.quantity

        if qty <= 0:
            report.add_error(
                "Quantity must be greater than zero."
            )
            return

        if qty > self.max_quantity:
            report.add_error(
                f"Quantity exceeds maximum ({self.max_quantity})."
            )

    # ======================================================
    # Price
    # ======================================================

    def _validate_price(
        self,
        request: ExecutionRequest,
        report: ValidationReport,
    ) -> None:

        if request.order_type == OrderType.MARKET:
            return

        if request.price is None:
            report.add_error(
                "Price is required."
            )
            return

        if request.price <= self.min_price:
            report.add_error(
                "Price must be positive."
            )

        if request.price > self.max_price:
            report.add_error(
                f"Price exceeds maximum ({self.max_price})."
            )

    # ======================================================
    # Stop Price
    # ======================================================

    def _validate_stop_price(
        self,
        request: ExecutionRequest,
        report: ValidationReport,
    ) -> None:

        if request.stop_price is None:
            return

        if request.stop_price <= 0:
            report.add_error(
                "Stop price must be greater than zero."
            )

        if request.stop_price > self.max_price:
            report.add_error(
                "Stop price exceeds maximum."
            )

    # ======================================================
    # Slippage
    # ======================================================

    def _validate_slippage(
        self,
        request: ExecutionRequest,
        report: ValidationReport,
    ) -> None:

        if request.max_slippage < 0:
            report.add_error(
                "Negative slippage is invalid."
            )

        if request.max_slippage > self.max_slippage:
            report.add_warning(
                "Maximum slippage is unusually high."
            )

    # ======================================================
    # Timeout
    # ======================================================

    def _validate_timeout(
        self,
        request: ExecutionRequest,
        report: ValidationReport,
    ) -> None:

        if request.timeout_seconds <= 0:
            report.add_error(
                "Timeout must be greater than zero."
            )

        elif request.timeout_seconds > 300:
            report.add_warning(
                "Very large timeout."
            )

    # ======================================================
    # Client Order ID
    # ======================================================

    def _validate_client_order_id(
        self,
        request: ExecutionRequest,
        report: ValidationReport,
    ) -> None:

        if self.allow_empty_client_id:
            return

        if not request.client_order_id.strip():
            report.add_error(
                "Client order id is required."
            )

    # ======================================================
    # Order Rules
    # ======================================================

    def validate_order_rules(
        self,
        request: ExecutionRequest,
    ) -> None:

        if (
            request.order_type == OrderType.LIMIT
            and request.price is None
        ):
            raise InvalidPriceError(
                0.0,
                request.request_id,
            )

        if (
            request.quantity <= 0
        ):
            raise InvalidQuantityError(
                request.quantity,
                request.request_id,
            )

        if (
            not request.symbol.strip()
        ):
            raise InvalidSymbolError(
                request.symbol,
                request.request_id,
            )

        request.mark_validated()

    # ======================================================
    # Convenience
    # ======================================================

    def __call__(
        self,
        request: ExecutionRequest,
    ) -> ValidationReport:

        return self.validate(request)
