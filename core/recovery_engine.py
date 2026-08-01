from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
import pandas as pd


@dataclass
class RecoveryDecision:
    action: str
    reason: str


class RecoveryEngine:
    """
    مسؤول عن إدارة الصفقات التي دخلت منطقة الخسارة بشكل ذكي ومتقدم.
    
    تم دمج: 
    - فلاتر حماية البيانات والأسعار.
    - خروج ذكي عند التعادل وملاحقة الأرباح.
    - تصفير سليم لحالة الـ Recovery عند الخروج لتجنب تعليق الصفقات.
    """

    def __init__(
        self,
        max_recovery_days: int = 7,
        break_even_buffer: float = 0.004,
        emergency_loss_pct: float = 0.08,
    ):
        self.max_recovery_days = max_recovery_days
        self.break_even_buffer = break_even_buffer
        self.emergency_loss_pct = emergency_loss_pct

    # ---------------------------------------------------------

    def should_start_recovery(self, pnl_percent: float) -> bool:
        return pnl_percent <= -0.015

    # ---------------------------------------------------------

    def start_recovery(self, position, current_timestamp: Optional[float] = None) -> None:
        position.recovery_mode = True
        position.recovery_start_time = current_timestamp or datetime.now(timezone.utc).timestamp()

    # ---------------------------------------------------------

    def stop_recovery(self, position) -> None:
        position.recovery_mode = False
        position.recovery_start_time = 0.0

    # ---------------------------------------------------------

    def days_in_recovery(self, position, current_timestamp: Optional[float] = None) -> float:
        start_time = getattr(position, 'recovery_start_time', 0.0)
        if not start_time or start_time == 0.0:
            return 0.0

        now = current_timestamp or datetime.now(timezone.utc).timestamp()
        return (now - start_time) / 86400

    # ---------------------------------------------------------

    def recovery_score(self, indicators: Optional[pd.DataFrame]) -> int:
        if (
            indicators is None
            or (
                isinstance(indicators, pd.DataFrame)
                and indicators.empty
            )
        ):
            return 0

        try:
            score = 0
            if indicators["supertrend_trend"].iloc[-1]:
                score += 1
            if indicators["ema20"].iloc[-1] > indicators["ema50"].iloc[-1]:
                score += 1
            if indicators["macd_hist"].iloc[-1] > 0:
                score += 1
            if indicators["roc"].iloc[-1] > 0:
                score += 1
            if indicators["rsi"].iloc[-1] > 50:
                score += 1
            if indicators["relative_volume"].iloc[-1] >= 1.2:
                score += 1
            return score
            
        # الملاحظة 1: إزالة المتغير e لتجنب الكود غير المستخدم
        except Exception:
            return 0

    # ---------------------------------------------------------

    def should_exit(
        self,
        position,
        current_price: float,
        indicators: Optional[pd.DataFrame],
        market_regime: str = "BULL",
        current_timestamp: Optional[float] = None
    ) -> RecoveryDecision:

        if current_price <= 0:
            return RecoveryDecision(
                action="HOLD",
                reason="INVALID_PRICE",
            )

        if getattr(position, "entry_price", 0) <= 0:
            return RecoveryDecision(
                action="HOLD",
                reason="INVALID_ENTRY_PRICE",
            )

        if not getattr(position, 'recovery_mode', False):
            return RecoveryDecision(
                action="HOLD",
                reason="Recovery غير مفعل",
            )

        loss_pct = (position.entry_price - current_price) / position.entry_price
        
        # الملاحظة 2: تصفير الـ Recovery قبل الخروج (SELL أو HOLD - Completed)
        if loss_pct >= self.emergency_loss_pct:
            self.stop_recovery(position)
            return RecoveryDecision(
                action="SELL",
                reason="خسارة طارئة",
            )

        recovery = self.recovery_score(indicators)
        break_even_price = position.entry_price * (1 + self.break_even_buffer)
        
        if current_price >= break_even_price:
            if recovery >= 5:
                # الصفقة تعافت بقوة، نوقف وضع التعافي لتكمل كصفقة رابحة عادية
                self.stop_recovery(position)
                return RecoveryDecision(
                    action="HOLD",
                    reason="Recovery Completed",
                )
            
            # بيع عند التعادل إذا كان الزخم ضعيفاً
            self.stop_recovery(position)
            return RecoveryDecision(
                action="SELL",
                reason="عاد إلى التعادل",
            )

        if market_regime == "BEAR" and recovery < 3:
            self.stop_recovery(position)
            return RecoveryDecision(
                action="SELL",
                reason="Bear Market",
            )

        if self.days_in_recovery(position, current_timestamp) >= self.max_recovery_days:
            if recovery >= 4:
                return RecoveryDecision(
                    action="HOLD",
                    reason="Strong Recovery",
                )
            self.stop_recovery(position)
            return RecoveryDecision(
                action="SELL",
                reason="Recovery Timeout",
            )

        if recovery >= 5:
            return RecoveryDecision(
                action="HOLD",
                reason="Recovery Strong",
            )

        return RecoveryDecision(
            action="HOLD",
            reason="ما زال ينتظر التعافي",
        )
