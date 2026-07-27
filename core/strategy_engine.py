from dataclasses import dataclass
from typing import List


@dataclass
class StrategyResult:
    signal: str
    score: int
    reasons: List[str]


class StrategyEngine:

    def __init__(self):
        self.buy_threshold = 80
        self.sell_threshold = -50

    def evaluate(
        self,
        price: float,
        ema100: float,
        rsi: float,
        volume_ratio: float = 1.0,
        trend_strength: float = 1.0,
        market_regime: str = "NORMAL",
    ) -> StrategyResult:

        score = 0
        reasons = []

        # ==========================
        # EMA Trend
        # ==========================
        if price > ema100:
            score += 40
            reasons.append("السعر أعلى من EMA100")
        else:
            score -= 40
            reasons.append("السعر أسفل EMA100")

        # ==========================
        # RSI
        # ==========================
        if rsi < 35:
            score += 35
            reasons.append("تشبع بيعي")

        elif rsi < 45:
            score += 15
            reasons.append("RSI جيد للشراء")

        elif rsi > 70:
            score -= 40
            reasons.append("تشبع شرائي")

        # ==========================
        # Volume
        # ==========================
        if volume_ratio > 1.5:
            score += 10
            reasons.append("ارتفاع في حجم التداول")

        # ==========================
        # Trend Strength
        # ==========================
        if trend_strength > 1.2:
            score += 10
            reasons.append("اتجاه قوي")

        # ==========================
        # Market Regime
        # ==========================
        if market_regime == "BEAR":
            score -= 30
            reasons.append("السوق هابط")

        elif market_regime == "BULL":
            score += 20
            reasons.append("السوق صاعد")

        # ==========================
        # القرار النهائي
        # ==========================
        if score >= self.buy_threshold:
            signal = "BUY"

        elif score <= self.sell_threshold:
            signal = "SELL"

        else:
            signal = "HOLD"

        return StrategyResult(
            signal=signal,
            score=score,
            reasons=reasons,
        )
