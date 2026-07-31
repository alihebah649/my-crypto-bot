from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Optional

from core.execution_models import (
    ExecutionRequest,
    ExecutionResult,
    ExecutionStatistics,
)

from core.execution_validator import (
    ExecutionValidator,
)

from core.execution_adapter import (
    ExecutionAdapter,
)

from core.execution_exceptions import (
    ExecutionError,
    ExchangeConnectionError,
    NetworkError,
    TimeoutError,
)


# ==========================================================
# Execution Engine
# ==========================================================

class ExecutionEngine:
    """
    القلب الرئيسي لطبقة Execution.

    مسؤول عن:

    Strategy
        ↓
    Validation
        ↓
    Exchange Adapter
        ↓
    Execution Result

    دون أن يعرف أي شيء عن الاستراتيجية أو إدارة المخاطر.
    """

    def __init__(
        self,
        adapter: ExecutionAdapter,
        validator: Optional[
            ExecutionValidator
        ] = None,
    ) -> None:

        self._adapter = adapter

        self._validator = (
            validator
            if validator is not None
            else ExecutionValidator()
        )

        self._statistics = (
            ExecutionStatistics()
        )

        self._started_at = datetime.now(
            timezone.utc
        )

        self._connected = False

    # ======================================================
    # Properties
    # ======================================================

    @property
    def adapter(self) -> ExecutionAdapter:

        return self._adapter

    @property
    def validator(self) -> ExecutionValidator:

        return self._validator

    @property
    def statistics(
        self,
    ) -> ExecutionStatistics:

        return self._statistics

    @property
    def is_connected(self) -> bool:

        return (
            self._connected
            and
            self._adapter.is_connected()
        )

    # ======================================================
    # Connection
    # ======================================================

    def connect(self) -> None:

        if self.is_connected:
            return

        self._adapter.connect()

        # الاعتماد على حالة الـ Adapter الحقيقية للتأكد من نجاح الاتصال
        self._connected = self._adapter.is_connected()

    def disconnect(self) -> None:

        if not self._connected:
            return

        self._adapter.disconnect()

        self._connected = False

    def ensure_connection(self) -> None:

        if self.is_connected:
            return

        raise ExchangeConnectionError(
            "Execution adapter is not connected."
        )

    # ======================================================
    # Execute
    # ======================================================

    def execute(
        self,
        request: ExecutionRequest,
    ) -> ExecutionResult:
        """
        تنفيذ طلب واحد.

        Workflow:

        Request
            ↓
        Connection
            ↓
        Validation
            ↓
        Adapter
            ↓
        Statistics
            ↓
        Result
        """

        self.ensure_connection()

        self._validator.validate_or_raise(
            request
        )

        request.mark_validated()

        request.mark_submitted()

        result = self._adapter.execute(
            request
        )

        self._statistics.register(
            result
        )

        return result

    # ======================================================
    # Safe Execute
    # ======================================================

    def safe_execute(
        self,
        request: ExecutionRequest,
    ) -> ExecutionResult:
        """
        تنفيذ آمن.

        يعيد تمرير استثناءات ExecutionError مباشرة للأعلى ليتم التعامل معها،
        بينما يقوم بالتقاط أي استثناءات غير متوقعة أخرى وتغليفها داخل ExecutionError.
        """

        try:

            return self.execute(
                request
            )

        except ExecutionError:

            raise

        except Exception as exc:

            raise ExecutionError(
                message=str(exc),
                code="EXECUTION_ERROR",
                request_id=request.request_id,
            ) from exc

    # ======================================================
    # Execute With Retry
    # ======================================================

    def execute_with_retry(
        self,
        request: ExecutionRequest,
    ) -> ExecutionResult:
        """
        تنفيذ الطلب مع إعادة المحاولة
        حسب RetryPolicy الموجود داخل الطلب.
        """

        policy = request.retry_policy

        if not policy.enabled:
            return self.execute(request)

        retries = 0

        delay = policy.retry_delay

        while True:

            try:

                return self.execute(
                    request
                )

            except (ExchangeConnectionError, NetworkError, TimeoutError):
                # إعادة المحاولة فقط مع الأخطاء الشبكية المؤقتة التي يمكن حلها بالانتظار
                retries += 1

                if retries > policy.max_retry:
                    raise

                time.sleep(delay)

                if (
                    policy.exponential_backoff
                ):
                    delay = min(
                        delay * 2.0,
                        policy.max_delay,
                    )

    # ======================================================
    # Statistics
    # ======================================================

    def reset_statistics(
        self,
    ) -> None:

        self._statistics.reset()

    # ======================================================
    # Information
    # ======================================================

    @property
    def started_at(self):

        return self._started_at

    @property
    def uptime_seconds(
        self,
    ) -> float:

        return (

            datetime.now(
                timezone.utc
            )

            -

            self._started_at

        ).total_seconds()

    # ======================================================
    # Shutdown
    # ======================================================

    def shutdown(self) -> None:
        """
        إيقاف Execution Engine بشكل آمن.
        """

        if self.is_connected:
            self.disconnect()

    # ======================================================
    # Context Manager
    # ======================================================

    def __enter__(self):

        self.connect()

        return self

    def __exit__(
        self,
        exc_type,
        exc,
        tb,
    ) -> None:

        self.shutdown()

    # ======================================================
    # Convenience
    # ======================================================

    def __call__(
        self,
        request: ExecutionRequest,
    ) -> ExecutionResult:

        return self.execute_with_retry(
            request
        )

    def __repr__(
        self,
    ) -> str:

        return (
            f"{self.__class__.__name__}("
            f"exchange="
            f"{self.adapter.exchange_name}, "
            f"connected="
            f"{self.is_connected})"
        )
