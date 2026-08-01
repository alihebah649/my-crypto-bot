from dataclasses import dataclass
from typing import Optional

from core.models import (
    TradeSignal,
    TradeType,
)


@dataclass
class StrategyDecision:
    """
    القرار النهائي للاستراتيجية.
    """

    signal: TradeSignal

    trade_type: Optional[TradeType]

    confidence: float

    score: int

    stop_loss: float

    take_profit: float

    reason: str


class StrategyEngine:
    """
    محرك اتخاذ القرار.

    يقوم بتحويل المؤشرات الفنية
    إلى قرار تداول نهائي.
    """

    def __init__(

        self,

        minimum_confidence=70,

        btc_bear_threshold=90,

    ):

        self.minimum_confidence = (
            minimum_confidence
        )

        self.btc_bear_threshold = (
            btc_bear_threshold
        )

    # ==========================================================
    # BTC MARKET FILTER
    # ==========================================================

    def btc_market_filter(

        self,

        btc_indicators,

    ):

        score = 0

        if (

            btc_indicators["ema50"].iloc[-1]

            >

            btc_indicators["ema200"].iloc[-1]

        ):

            score += 1

        if (

            btc_indicators["supertrend_trend"].iloc[-1]

        ):

            score += 1

        if (

            btc_indicators["adx"].iloc[-1]

            > 25

        ):

            score += 1

        if (

            btc_indicators["rsi"].iloc[-1]

            > 50

        ):

            score += 1

        if score >= 3:

            return "BULL"

        if score == 2:

            return "NEUTRAL"

        return "BEAR"

    # ==========================================================
    # MULTI TIMEFRAME FILTER
    # ==========================================================

    def timeframe_confirmation(

        self,

        fast,

        slow,

    ):

        score = 0

        if (

            fast["ema20"].iloc[-1]

            >

            fast["ema50"].iloc[-1]

        ):

            score += 1

        if (

            slow["ema20"].iloc[-1]

            >

            slow["ema50"].iloc[-1]

        ):

            score += 1

        if (

            fast["supertrend_trend"].iloc[-1]

        ):

            score += 1

        if (

            slow["supertrend_trend"].iloc[-1]

        ):

            score += 1

        return score

    # ==========================================================
    # SMART TRADE FILTER
    # ==========================================================

    def smart_trade_filter(

        self,

        indicators,

        trend_strength: int,

        momentum_score: int,

    ):

        score = 0

        reason = []

        # التعديل: الاعتماد المباشر على المتغيرات المحلية الممررة
        if trend_strength >= 3:

            score += 20

            reason.append(
                "TREND"
            )

        if momentum_score >= 3:

            score += 20

            reason.append(
                "MOMENTUM"
            )

        if (
            indicators["adx"].iloc[-1]
            >= 25
        ):

            score += 10

            reason.append(
                "ADX"
            )

        if (
            indicators["relative_volume"].iloc[-1]
            >= 1.20
        ):

            score += 10

            reason.append(
                "VOLUME"
            )

        if (
            indicators["roc"].iloc[-1]
            > 0
        ):

            score += 10

            reason.append(
                "ROC"
            )

        if (
            indicators["macd_hist"].iloc[-1]
            > 0
        ):

            score += 10

            reason.append(
                "MACD"
            )

        if (
            indicators["rsi"].iloc[-1]
            > 55
        ):

            score += 5

            reason.append(
                "RSI"
            )

        if (
            indicators["stochastic_rsi"].iloc[-1]
            > 50
        ):

            score += 5

            reason.append(
                "STOCH_RSI"
            )

        if (
            indicators["supertrend_trend"].iloc[-1]
        ):

            score += 10

            reason.append(
                "SUPERTREND"
            )

        return score, reason

    # ==========================================================
    # TRADE TYPE
    # ==========================================================

    def choose_trade_type(

        self,

        indicators,

    ):

        adx = indicators["adx"].iloc[-1]

        atr = indicators["atr"].iloc[-1]

        roc = indicators["roc"].iloc[-1]

        volume = indicators[
            "relative_volume"
        ].iloc[-1]

        if (

            adx >= 35

            and

            volume >= 1.50

            and

            abs(roc) >= 2

        ):

            return TradeType.SCALPING

        if (

            adx >= 25

            and

            atr > 0

        ):

            return TradeType.SWING

        return None

    # ==========================================================
    # CONFIDENCE
    # ==========================================================

    def confidence(

        self,

        score,

    ):

        confidence = min(

            100,

            score,

        )

        return float(

            confidence

        )

    # ==========================================================
    # MARKET REGIME FILTER
    # ==========================================================

    def market_regime_filter(
        self,
        trend_strength: int,
    ):

        # التعديل: استقبال القيمة كـ int مباشرة
        if trend_strength >= 4:
            return "STRONG_TREND"

        if trend_strength == 3:
            return "TREND"

        if trend_strength == 2:
            return "RANGE"

        return "WEAK"

    # ==========================================================
    # VOLATILITY FILTER
    # ==========================================================

    def volatility_filter(
        self,
        indicators,
    ):

        atr = indicators["atr"].iloc[-1]

        close = indicators["ema20"].iloc[-1]

        if close <= 0:
            return False

        volatility = atr / close

        return (

            0.003

            <=

            volatility

            <=

            0.08

        )

    # ==========================================================
    # LIQUIDITY FILTER
    # ==========================================================

    def liquidity_filter(
        self,
        indicators,
    ):

        volume = indicators[
            "relative_volume"
        ].iloc[-1]

        return volume >= 1.10

    # ==========================================================
    # TREND QUALITY FILTER
    # ==========================================================

    def trend_quality_filter(
        self,
        indicators,
    ):

        ema20 = indicators["ema20"].iloc[-1]

        ema50 = indicators["ema50"].iloc[-1]

        ema200 = indicators["ema200"].iloc[-1]

        adx = indicators["adx"].iloc[-1]

        if adx < 20:
            return False

        if not (

            ema20

            >

            ema50

            >

            ema200

        ):

            return False

        return True

    # ==========================================================
    # MOMENTUM FILTER
    # ==========================================================

    def momentum_filter(
        self,
        indicators,
    ):

        return (

            indicators["macd_hist"].iloc[-1] > 0

            and

            indicators["roc"].iloc[-1] > 0

            and

            indicators["rsi"].iloc[-1] > 55

        )

    # ==========================================================
    # RISK / REWARD FILTER
    # ==========================================================

    def risk_reward_filter(
        self,
        entry_price,
        stop_loss,
        take_profit,
        minimum_rr=2.0,
    ):

        risk = (

            entry_price

            -

            stop_loss

        )

        reward = (

            take_profit

            -

            entry_price

        )

        if risk <= 0:
            return False

        rr = reward / risk

        return rr >= minimum_rr

    # ==========================================================
    # STOP LOSS
    # ==========================================================

    def calculate_stop_loss(

        self,

        entry_price,

        atr,

    ):

        return (

            entry_price

            -

            atr * 2

        )

    # ==========================================================
    # TAKE PROFIT
    # ==========================================================

    def calculate_take_profit(

        self,

        entry_price,

        atr,

        trade_type,

    ):

        if trade_type == TradeType.SCALPING:

            rr = 2.0

        elif trade_type == TradeType.SWING:

            rr = 3.0

        elif trade_type == TradeType.SCALPING_SWING:

            rr = 4.0

        else:

            rr = 2.5

        return (

            entry_price

            +

            atr * rr * 2

        )

    # ==========================================================
    # FINAL DECISION
    # ==========================================================

    def evaluate(

        self,

        indicators,

        btc_indicators,

        fast_tf,

        slow_tf,

        entry_price,

    ):

        # -------------------------------
        # التعديل الرئيسي: استخراج القيم الفردية مرة واحدة في البداية
        # -------------------------------
        trend_strength = int(indicators["trend_strength"].iloc[-1])
        momentum_score = int(indicators["momentum_score"].iloc[-1])

        # -------------------------------
        # BTC FILTER
        # -------------------------------

        market = self.btc_market_filter(
            btc_indicators,
        )

        # -------------------------------
        # MARKET REGIME
        # -------------------------------

        regime = self.market_regime_filter(
            trend_strength,
        )

        if regime == "WEAK":

            return StrategyDecision(

                signal=TradeSignal.HOLD,

                trade_type=None,

                confidence=0.0,

                score=0,

                stop_loss=0,

                take_profit=0,

                reason="WEAK_MARKET",

            )

        # -------------------------------
        # VOLATILITY FILTER
        # -------------------------------

        if not self.volatility_filter(
            indicators,
        ):

            return StrategyDecision(

                signal=TradeSignal.HOLD,

                trade_type=None,

                confidence=0.0,

                score=0,

                stop_loss=0,

                take_profit=0,

                reason="LOW_VOLATILITY",

            )

        # -------------------------------
        # LIQUIDITY FILTER
        # -------------------------------

        if not self.liquidity_filter(
            indicators,
        ):

            return StrategyDecision(

                signal=TradeSignal.HOLD,

                trade_type=None,

                confidence=0.0,

                score=0,

                stop_loss=0,

                take_profit=0,

                reason="LOW_LIQUIDITY",

            )

        # -------------------------------
        # TREND QUALITY
        # -------------------------------

        if not self.trend_quality_filter(
            indicators,
        ):

            return StrategyDecision(

                signal=TradeSignal.HOLD,

                trade_type=None,

                confidence=0.0,

                score=0,

                stop_loss=0,

                take_profit=0,

                reason="BAD_TREND",

            )

        # -------------------------------
        # MOMENTUM FILTER
        # -------------------------------

        if not self.momentum_filter(
            indicators,
        ):

            return StrategyDecision(

                signal=TradeSignal.HOLD,

                trade_type=None,

                confidence=0.0,

                score=0,

                stop_loss=0,

                take_profit=0,

                reason="WEAK_MOMENTUM",

            )

        # -------------------------------
        # MULTI TIMEFRAME
        # -------------------------------

        timeframe_score = (

            self.timeframe_confirmation(

                fast_tf,

                slow_tf,

            )

        )

        # -------------------------------
        # MAIN SCORE
        # -------------------------------

        score = 0

        reasons = []

        base_score, base_reasons = (

            self.smart_trade_filter(

                indicators,

                trend_strength,

                momentum_score,

            )

        )

        score += base_score

        reasons.extend(base_reasons)

        # -------------------------------
        # Multi Timeframe Bonus
        # -------------------------------

        score += timeframe_score * 5

        # -------------------------------
        # Strong Trend Bonus
        # -------------------------------

        # التعديل: مقارنة المتغير المحلي النظيف
        if trend_strength >= 4:

            score += 10

            reasons.append(
                "STRONG_TREND"
            )

        elif trend_strength == 3:

            score += 5

        # -------------------------------
        # Strong Momentum Bonus
        # -------------------------------

        # التعديل: مقارنة المتغير المحلي النظيف
        if momentum_score >= 4:

            score += 10

            reasons.append(
                "STRONG_MOMENTUM"
            )

        elif momentum_score == 3:

            score += 5

        # -------------------------------
        # High ADX Bonus
        # -------------------------------

        adx = indicators["adx"].iloc[-1]

        if adx >= 40:

            score += 10

            reasons.append(
                "ADX40"
            )

        elif adx >= 30:

            score += 5

        # -------------------------------
        # High Volume Bonus
        # -------------------------------

        rv = indicators [
            "relative_volume"
        ].iloc[-1]

        if rv >= 2.0:

            score += 10

            reasons.append(
                "HIGH_VOLUME"
            )

        elif rv >= 1.5:

            score += 5

        # -------------------------------
        # SuperTrend Bonus
        # -------------------------------

        if indicators [
            "supertrend_trend"
        ].iloc[-1]:

            score += 5

        # -------------------------------
        # Confidence
        # -------------------------------

        current_confidence = self.confidence(
            score
        )

        # -------------------------------
        # BTC BEAR FILTER
        # -------------------------------

        if (

            market == "BEAR"

            and

            current_confidence

            <

            self.btc_bear_threshold

        ):

            return StrategyDecision(

                signal=TradeSignal.HOLD,

                trade_type=None,

                confidence=current_confidence,

                score=score,

                stop_loss=0,

                take_profit=0,

                reason="BTC_BEAR_FILTER",

            )

        # -------------------------------
        # Minimum Confidence
        # -------------------------------

        if (

            current_confidence

            <

            self.minimum_confidence

        ):

            return StrategyDecision(

                signal=TradeSignal.HOLD,

                trade_type=None,

                confidence=current_confidence,

                score=score,

                stop_loss=0,

                take_profit=0,

                reason="LOW_CONFIDENCE",

            )

        # -------------------------------
        # Trade Type
        # -------------------------------

        trade_type = self.choose_trade_type(

            indicators,

        )

        if trade_type is None:

            return StrategyDecision(

                signal=TradeSignal.HOLD,

                trade_type=None,

                confidence=current_confidence,

                score=score,

                stop_loss=0,

                take_profit=0,

                reason="NO_SETUP",

            )

        # -------------------------------
        # Strong Signal (تعديل الـ Scalping Swing)
        # -------------------------------

        # التعديل: استخدام المتغيرات المحلية النظيفة هنا أيضاً
        if (

            current_confidence >= 90

            and

            trend_strength >= 4

            and

            momentum_score >= 4

        ):

            trade_type = TradeType.SCALPING_SWING

        # -------------------------------
        # ATR
        # -------------------------------

        atr = indicators["atr"].iloc[-1]

        stop_loss = (

            self.calculate_stop_loss(

                entry_price,

                atr,

            )

        )

        take_profit = (

            self.calculate_take_profit(

                entry_price,

                atr,

                trade_type,

            )

        )

        # -------------------------------
        # Risk / Reward Validation
        # -------------------------------

        minimum_rr = (

            2.5

            if trade_type == TradeType.SWING

            else

            2.0

        )

        if not self.risk_reward_filter(

            entry_price,

            stop_loss,

            take_profit,

            minimum_rr,

        ):

            return StrategyDecision(

                signal=TradeSignal.HOLD,

                trade_type=None,

                confidence=current_confidence,

                score=score,

                stop_loss=0,

                take_profit=0,

                reason="LOW_RISK_REWARD",

            )

        # -------------------------------
        # FINAL BUY
        # -------------------------------

        return StrategyDecision(

            signal=TradeSignal.BUY,

            trade_type=trade_type,

            confidence=current_confidence,

            score=score,

            stop_loss=stop_loss,

            take_profit=take_profit,

            reason="|".join(

                reasons,

            ),

        )
