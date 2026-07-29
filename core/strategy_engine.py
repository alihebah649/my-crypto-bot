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

    ):

        score = 0

        reason = []

        if (
            indicators["trend_strength"] >= 3
        ):

            score += 20

            reason.append(
                "TREND"
            )

        if (
            indicators["momentum_score"] >= 3
        ):

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

        else:

            rr = 3.0

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
        # BTC FILTER
        # -------------------------------

        market = self.btc_market_filter(

            btc_indicators,

        )

        # -------------------------------
        # MULTI TF
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

        score, reasons = (

            self.smart_trade_filter(

                indicators,

            )

        )

        score += timeframe_score * 5

        confidence = self.confidence(

            score,

        )

        # -------------------------------
        # BTC BEAR FILTER
        # -------------------------------

        if (

            market == "BEAR"

            and

            confidence

            <

            self.btc_bear_threshold

        ):

            return StrategyDecision(

                signal=TradeSignal.HOLD,

                trade_type=None,

                confidence=confidence,

                score=score,

                stop_loss=0,

                take_profit=0,

                reason="BTC_BEAR_FILTER",

            )

        # -------------------------------
        # Minimum Confidence
        # -------------------------------

        if (

            confidence

            <

            self.minimum_confidence

        ):

            return StrategyDecision(

                signal=TradeSignal.HOLD,

                trade_type=None,

                confidence=confidence,

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

                confidence=confidence,

                score=score,

                stop_loss=0,

                take_profit=0,

                reason="NO_SETUP",

            )

        # -------------------------------
        # Strong Signal
        # -------------------------------

        if (

            confidence >= 90

            and

            indicators["trend_strength"] >= 4

            and

            indicators["momentum_score"] >= 4

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
        # FINAL BUY
        # -------------------------------

        return StrategyDecision(

            signal=TradeSignal.BUY,

            trade_type=trade_type,

            confidence=confidence,

            score=score,

            stop_loss=stop_loss,

            take_profit=take_profit,

            reason="|".join(

                reasons,

            ),

        )
