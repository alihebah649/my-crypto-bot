from dataclasses import dataclass
from typing import Dict, Any, Optional, List  # 3) تم إضافة List لضمان النوع الصارم Typed بالكامل

from core.models import (
    TradeType,
    RiskLevel,
)


@dataclass
class RiskDecision:
    """نتيجة قرار إدارة المخاطرة المحدثة بتفاصيل دقيقة."""
    allowed: bool
    position_size: float
    risk_level: RiskLevel
    reason_code: str


class RiskEngine:
    """
    محرك إدارة رأس المال والمخاطرة الاحترافي - الإصدار الأول (v1.0.0).
    """

    def __init__(
        self,
        max_portfolio_exposure: float = 0.70,
        exposure_buffer: float = 0.005,  # هامش أمان بنسبة 0.5% لتفادي فروقات الكسور
        max_open_trades: int = 10,
    ):
        self.max_portfolio_exposure = max_portfolio_exposure
        self.exposure_buffer = exposure_buffer
        self.max_open_trades = max_open_trades

    # ==========================================================
    # التحقق من عدد الصفقات المفتوحة
    # ==========================================================
    def can_open_trade(self, open_positions: int) -> bool:
        return open_positions < self.max_open_trades

    # ==========================================================
    # الحد الأقصى الديناميكي لحجم الصفقة بناءً على المخاطرة
    # ==========================================================
    def get_dynamic_max_position_size(self, risk_level: RiskLevel) -> float:
        if risk_level == RiskLevel.LOW:
            return 0.12  # 12% من الـ Equity
        elif risk_level == RiskLevel.MEDIUM:
            return 0.08  # 8% من الـ Equity
        else:
            return 0.05  # 5% من الـ Equity

    # ==========================================================
    # تحديد مستوى المخاطرة المتطور والتحقق من حالة السوق
    # ==========================================================
    def calculate_risk_level(
        self,
        confidence: float,
        volatility: float,
        market_regime: Dict[str, Any],
    ) -> RiskLevel:
        score = 0

        # قوة الإشارة والثقة
        if confidence >= 90:
            score += 2
        elif confidence >= 75:
            score += 1
        elif confidence < 50:
            score -= 2
        else:
            score -= 1

        # التقلب (Volatility)
        if volatility < 0.03:
            score += 1
        elif volatility > 0.12:
            score -= 3
        elif volatility > 0.08:
            score -= 2

        # مؤشرات هيكل السوق المتقدمة
        adx = market_regime.get("adx", 25)
        trend_score = market_regime.get("trend_score", 0)
        btc_regime = market_regime.get("btc_regime", "BULLISH")
        
        btc_dominance = market_regime.get("btc_dominance", 50.0)
        usdt_dominance = market_regime.get("usdt_dominance", 5.0)
        fear_and_greed = market_regime.get("fear_and_greed", 50)
        total_market_trend = market_regime.get("total_market_trend", "UPTREND")

        if adx > 25 and trend_score > 0 and total_market_trend == "UPTREND":
            score += 2
        elif total_market_trend == "DOWNTREND":
            score -= 2

        if usdt_dominance > 7.0: 
            score -= 2 
        
        if fear_and_greed < 25: 
            score -= 1 
        elif fear_and_greed > 85: 
            score -= 1 

        if btc_regime == "BULLISH":
            score += 1
        elif btc_regime == "BEARISH":
            score -= 2

        if score >= 3:
            return RiskLevel.LOW
        elif score <= 0:
            return RiskLevel.HIGH
        return RiskLevel.MEDIUM

    # ==========================================================
    # حساب النسبة الأساسية لحجم الصفقة
    # ==========================================================
    def calculate_base_percentage(
        self,
        confidence: float,
        trade_type: TradeType,
        risk_level: RiskLevel,
    ) -> float:
        max_position = self.get_dynamic_max_position_size(risk_level)
        base_percentage = max_position

        if trade_type == TradeType.SCALPING:
            base_percentage *= 0.7
        elif trade_type == TradeType.SWING:
            base_percentage *= 1.0
        elif trade_type == TradeType.SCALPING_SWING:
            base_percentage *= 1.1

        if risk_level == RiskLevel.LOW:
            multiplier = 1.0
        elif risk_level == RiskLevel.MEDIUM:
            multiplier = 0.75
        else:
            multiplier = 0.40

        # معادلة الثقة المستمرة (Continuous Multiplier) لضمان سلاسة التغيير
        confidence_multiplier = 0.5 + (confidence / 200.0)

        return base_percentage * multiplier * confidence_multiplier

    # ==========================================================
    # تعديل الـ ATR بدالة مستقلة
    # ==========================================================
    def apply_atr_adjustment(self, position_size: float, atr_percent: float) -> float:
        if atr_percent <= 0:
            return position_size
        if atr_percent >= 0.12:
            return position_size * 0.35
        if atr_percent >= 0.08:
            return position_size * 0.50
        if atr_percent >= 0.05:
            return position_size * 0.70
        if atr_percent >= 0.03:
            return position_size * 0.85
        return position_size

    # ==========================================================
    # فلتر حماية المحفظة عند انهيار البيتكوين
    # ==========================================================
    def is_btc_collapsing(self, market_regime: Dict[str, Any]) -> bool:
        btc_regime = market_regime.get("btc_regime", "BULLISH")
        
        # TODO: btc_crash_signal generated by Market Regime Engine (e.g., sharp 1h drop threshold)
        btc_crash_signal = market_regime.get("btc_crash_signal", False) 
        
        return btc_regime == "BEARISH" and btc_crash_signal

    # ==========================================================
    # فحص الارتباط المؤقت (Correlation)
    # ==========================================================
    def check_correlation_limit(self, symbol: str, current_open_symbols: List[str]) -> bool:
        """
        TODO: Build a real Correlation Matrix logic here later.
        Temporarily returns True to avoid blocking un-correlated assets.
        """
        return True

    # ==========================================================
    # نظام الـ Recovery الفلتر الذكي والمتوافق
    # ==========================================================
    def recovery_allowed(self, symbol: str, recovery_engine: Optional[Any] = None) -> bool:
        if recovery_engine is None:
            return True
        
        if hasattr(recovery_engine, 'can_recover'):
            return recovery_engine.can_recover(symbol)
        
        return True

    # ==========================================================
    # القرار النهائي والتقييم المشدد
    # ==========================================================
    def evaluate_trade(
        self,
        symbol: str,
        equity: float,
        free_balance: float,
        confidence: float,
        volatility: float,
        trade_type: TradeType,
        current_market_value_exposure: float,  # 1) تنبيه هندسي: يجب تمرير snapshot.market_value حصراً من الـ PortfolioEngine
        open_positions: int,
        current_open_symbols: List[str],      # 3) تم تعديل النوع هنا ليصبح List[str] بشكل صارم ومحمي
        atr_percent: float,
        min_notional: float,                   # 2) تم نقله هنا ليكون ديناميكياً وقادماً من الـ ExchangeInfo لكل زوج
        market_regime: Dict[str, Any],
        recovery_engine: Optional[Any] = None,
    ) -> RiskDecision:
        
        # صمامات الأمان وحماية البيانات المدخلة (Sanity & Integrity Checks)
        if equity <= 0:
            return RiskDecision(allowed=False, position_size=0.0, risk_level=RiskLevel.HIGH, reason_code="ERR_INVALID_EQUITY")
        if free_balance <= 0:
            return RiskDecision(allowed=False, position_size=0.0, risk_level=RiskLevel.HIGH, reason_code="ERR_INVALID_FREE_BALANCE")
        if confidence <= 0 or confidence > 100:
            return RiskDecision(allowed=False, position_size=0.0, risk_level=RiskLevel.HIGH, reason_code="ERR_INVALID_CONFIDENCE")
        if atr_percent < 0:
            return RiskDecision(allowed=False, position_size=0.0, risk_level=RiskLevel.HIGH, reason_code="ERR_INVALID_ATR_PERCENT")
        if volatility > 1.0 or volatility < 0: 
            return RiskDecision(allowed=False, position_size=0.0, risk_level=RiskLevel.HIGH, reason_code="ERR_INVALID_VOLATILITY")
        if current_market_value_exposure < 0: 
            return RiskDecision(allowed=False, position_size=0.0, risk_level=RiskLevel.HIGH, reason_code="ERR_INVALID_EXPOSURE")
        if min_notional <= 0:
            return RiskDecision(allowed=False, position_size=0.0, risk_level=RiskLevel.HIGH, reason_code="ERR_INVALID_MIN_NOTIONAL")

        # معالجة المشكلة المنطقية للـ Min Notional لحسابات الـ Equity الصغيرة جداً
        if equity < min_notional:
            return RiskDecision(
                allowed=False, 
                position_size=0.0, 
                risk_level=RiskLevel.HIGH, 
                reason_code="REJECT_EQUITY_LESS_THAN_MIN_NOTIONAL"
            )

        # حظر الدخول الشامل عند انهيار البيتكوين
        if self.is_btc_collapsing(market_regime):
            return RiskDecision(allowed=False, position_size=0.0, risk_level=RiskLevel.HIGH, reason_code="REJECT_BTC_COLLAPSE")

        # فحص الفلتر الذكي للـ Recovery
        if not self.recovery_allowed(symbol, recovery_engine):
            return RiskDecision(allowed=False, position_size=0.0, risk_level=RiskLevel.HIGH, reason_code="REJECT_RECOVERY_RESTRICTED")

        # فحص عدد الصفقات المفتوحة
        if not self.can_open_trade(open_positions):
            return RiskDecision(allowed=False, position_size=0.0, risk_level=RiskLevel.HIGH, reason_code="REJECT_MAX_OPEN_TRADES")

        # فحص فلتر الارتباط
        if not self.check_correlation_limit(symbol, current_open_symbols):
            return RiskDecision(allowed=False, position_size=0.0, risk_level=RiskLevel.HIGH, reason_code="REJECT_HIGH_CORRELATION")

        # حساب مستوى المخاطرة والنسبة المستهدفة
        risk_level = self.calculate_risk_level(confidence, volatility, market_regime)
        target_percentage = self.calculate_base_percentage(confidence, trade_type, risk_level)
        
        # تحويل النسبة لقيمة مالية معتمدة على الـ Equity
        position_size = equity * target_percentage
        
        # استدعاء الدالة المستقلة لتعديل الـ ATR
        position_size = self.apply_atr_adjustment(position_size, atr_percent)

        # تطبيق الحدود القصوى الديناميكية بناءً على الـ Equity ومستوى المخاطرة
        max_allowed_size = equity * self.get_dynamic_max_position_size(risk_level)
        if position_size > max_allowed_size:
            position_size = max_allowed_size

        # تطبيق الحجم الأدنى المقاس بالـ Notional الفعلي المستلم ديناميكياً للزوج
        if position_size < min_notional:
            position_size = min_notional

        # التحقق الحاسم من توفر السيولة الحرة (Free Balance Check)
        if free_balance < position_size:
            return RiskDecision(
                allowed=False, 
                position_size=0.0, 
                risk_level=risk_level, 
                reason_code="REJECT_INSUFFICIENT_FREE_BALANCE"
            )

        # فحص التعرض الإجمالي القائم على الـ Market Value الفعلي للمحفظة مع هامش الأمان
        total_exposure = current_market_value_exposure + position_size
        safe_exposure_limit = equity * (self.max_portfolio_exposure - self.exposure_buffer)
        
        if total_exposure > safe_exposure_limit:
            return RiskDecision(
                allowed=False, 
                position_size=0.0, 
                risk_level=risk_level, 
                reason_code="REJECT_MAX_EXPOSURE_LIMIT"
            )

        # توليد كود الـ reason_code المختصر والمثالي لتحليلات السجلات
        confidence_suffix = "HIGHCONF" if confidence >= 90 else "MIDCONF"
        generated_reason_code = f"APPROVED_{risk_level.name}_{confidence_suffix}"

        return RiskDecision(
            allowed=True,
            position_size=position_size,  # ممرر خام ليتعامل معه الـ Order Executor بناءً على قواعد المنصة بدقة
            risk_level=risk_level,
            reason_code=generated_reason_code,
        )