from dataclasses import dataclass
from typing import Optional

from core.models import (
    TradeType,
    RiskLevel,
)


@dataclass
class RiskDecision:
    """
    نتيجة قرار إدارة المخاطرة.
    """

    allowed: bool
    position_size: float
    risk_level: RiskLevel
    reason: str


class RiskEngine:
    """
    محرك إدارة رأس المال والمخاطرة.

    مسؤول عن:
    - تحديد حجم الصفقة.
    - منع المخاطرة الزائدة.
    - توزيع رأس المال بين Scalping و Swing.
    - التحكم في Recovery.
    """

    def __init__(
        self,
        max_portfolio_exposure: float = 0.70,
        max_position_size: float = 0.10,
        min_position_size: float = 0.02,
        max_open_trades: int = 8,
    ):
        self.max_portfolio_exposure = max_portfolio_exposure
        self.max_position_size = max_position_size
        self.min_position_size = min_position_size
        self.max_open_trades = max_open_trades


    # ==========================================================
    # تحديد مستوى المخاطرة
    # ==========================================================

    def calculate_risk_level(
        self,
        confidence: float,
        volatility: float,
        market_strength: float,
    ) -> RiskLevel:
        score = 0

        # قوة الإشارة
        if confidence >= 90:
            score += 2
        elif confidence >= 75:
            score += 1
        else:
            score -= 1

        # التقلب
        if volatility < 0.03:
            score += 1
        elif volatility > 0.08:
            score -= 1

        # قوة السوق
        if market_strength > 1.2:
            score += 1
        elif market_strength < 0.8:
            score -= 1

        if score >= 3:
            return RiskLevel.LOW
        elif score <= 0:
            return RiskLevel.HIGH
        return RiskLevel.MEDIUM


    # ==========================================================
    # حساب الحجم الأساسي للصفقة
    # ==========================================================

    def calculate_position_size(
        self,
        balance: float,
        confidence: float,
        trade_type: TradeType,
        risk_level: RiskLevel,
    ) -> float:

        base_percentage = self.max_position_size

        # تعديل حسب نوع الصفقة
        if trade_type == TradeType.SCALPING:
            base_percentage *= 0.7
        elif trade_type == TradeType.SWING:
            base_percentage *= 1.0

        # تعديل حسب المخاطرة
        if risk_level == RiskLevel.LOW:
            multiplier = 1.0
        elif risk_level == RiskLevel.MEDIUM:
            multiplier = 0.7
        else:
            multiplier = 0.35

        # تعديل حسب الثقة
        confidence_multiplier = confidence / 100

        final_percentage = (
            base_percentage
            *
            multiplier
            *
            confidence_multiplier
        )

        # الحد الأدنى والأقصى
        if final_percentage < self.min_position_size:
            final_percentage = self.min_position_size

        if final_percentage > self.max_position_size:
            final_percentage = self.max_position_size

        return (
            balance
            *
            final_percentage
        )

    # ==========================================================
    # التحقق من الحد الأقصى للتعرض
    # ==========================================================

    def exposure_allowed(
        self,
        balance: float,
        current_exposure: float,
        new_position_size: float,
    ) -> bool:
        total = (
            current_exposure
            + new_position_size
        )
        return (
            total
            <=
            balance
            * self.max_portfolio_exposure
        )

    # ==========================================================
    # الحد الأقصى لعدد الصفقات
    # ==========================================================

    def can_open_trade(
        self,
        open_positions: int,
    ) -> bool:
        return (
            open_positions
            <
            self.max_open_trades
        )

    # ==========================================================
    # تعديل الحجم باستخدام ATR
    # ==========================================================

    def apply_atr_adjustment(
        self,
        position_size: float,
        atr_percent: float,
    ) -> float:
        if atr_percent <= 0:
            return position_size
        if atr_percent >= 0.08:
            return (
                position_size
                * 0.50
            )
        if atr_percent >= 0.05:
            return (
                position_size
                * 0.70
            )
        if atr_percent >= 0.03:
            return (
                position_size
                * 0.85
            )
        return position_size

    # ==========================================================
    # Recovery Filter
    # ==========================================================

    def recovery_allowed(
        self,
        symbol: str,
        allowed_symbols,
    ) -> bool:
        return (
            symbol
            in
            allowed_symbols
        )

    # ==========================================================
    # القرار النهائي
    # ==========================================================

    def evaluate_trade(
        self,
        balance: float,
        confidence: float,
        volatility: float,
        market_strength: float,
        trade_type: TradeType,
        current_exposure: float,
        open_positions: int,
        atr_percent: float,
    ) -> RiskDecision:
        risk_level = self.calculate_risk_level(
            confidence,
            volatility,
            market_strength,
        )
        position_size = (
            self.calculate_position_size(
                balance,
                confidence,
                trade_type,
                risk_level,
            )
        )
        position_size = (
            self.apply_atr_adjustment(
                position_size,
                atr_percent,
            )
        )
        if not self.can_open_trade(
            open_positions,
        ):
            return RiskDecision(
                allowed=False,
                position_size=0.0,
                risk_level=risk_level,
                reason="MAX_OPEN_TRADES",
            )
        if not self.exposure_allowed(
            balance,
            current_exposure,
            position_size,
        ):
            return RiskDecision(
                allowed=False,
                position_size=0.0,
                risk_level=risk_level,
                reason="MAX_EXPOSURE",
            )
        return RiskDecision(
            allowed=True,
            position_size=round(position_size, 2),
            risk_level=risk_level,
            reason="APPROVED",
        )
