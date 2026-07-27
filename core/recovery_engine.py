from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from core.portfolio_engine import Position


@dataclass
class RecoveryDecision:
    action: str
    reason: str


class RecoveryEngine:
    """
    مسؤول عن إدارة الصفقات التي دخلت منطقة الخسارة.

    لا يبيع مباشرة وإنما يحاول إعطاء الصفقة فرصة للتعافي
    طالما أن ظروف السوق ما زالت مناسبة.
    """

    def __init__(
        self,
        max_recovery_days: int = 7,
        break_even_buffer: float = 0.002,
        emergency_loss_pct: float = 0.08,
    ):
        self.max_recovery_days = max_recovery_days
        self.break_even_buffer = break_even_buffer
        self.emergency_loss_pct = emergency_loss_pct

    # ---------------------------------------------------------

    def start_recovery(
        self,
        position: Position,
    ):

        position.recovery_mode = True

        position.recovery_start_time = datetime.now(
            timezone.utc
        ).timestamp()

    # ---------------------------------------------------------

    def stop_recovery(
        self,
        position: Position,
    ):

        position.recovery_mode = False

        position.recovery_start_time = 0.0

    # ---------------------------------------------------------

    def days_in_recovery(
        self,
        position: Position,
    ) -> float:

        if position.recovery_start_time == 0:
            return 0.0

        now = datetime.now(
            timezone.utc
        ).timestamp()

        return (
            now - position.recovery_start_time
        ) / 86400

    # ---------------------------------------------------------

    def should_exit(
        self,
        position: Position,
        current_price: float,
        market_regime: str = "BULL",
    ) -> RecoveryDecision:

        # =====================================
        # لم يدخل Recovery بعد
        # =====================================

        if not position.recovery_mode:

            return RecoveryDecision(
                action="HOLD",
                reason="Recovery غير مفعل",
            )

        # =====================================
        # خرج عند نقطة التعادل
        # =====================================

        break_even_price = (
            position.entry_price
            * (1 + self.break_even_buffer)
        )

        if current_price >= break_even_price:

            return RecoveryDecision(
                action="SELL",
                reason="عاد إلى التعادل",
            )

        # =====================================
        # انهيار السوق
        # =====================================

        if market_regime == "BEAR":

            return RecoveryDecision(
                action="SELL",
                reason="السوق أصبح هابطاً",
            )

        # =====================================
        # خسارة طارئة
        # =====================================

        loss_pct = (
            position.entry_price
            - current_price
        ) / position.entry_price

        if loss_pct >= self.emergency_loss_pct:

            return RecoveryDecision(
                action="SELL",
                reason="خسارة طارئة",
            )

        # =====================================
        # انتهاء مدة Recovery
        # =====================================

        if (
            self.days_in_recovery(position)
            >= self.max_recovery_days
        ):

            return RecoveryDecision(
                action="SELL",
                reason="انتهاء مدة Recovery",
            )

        # =====================================

        return RecoveryDecision(
            action="HOLD",
            reason="ما زال ينتظر التعافي",
        )
