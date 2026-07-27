from dataclasses import dataclass
from typing import List


@dataclass
class FilterResult:
    passed: bool
    score: int
    reasons: List[str]


class MarketFilter:

    def __init__(
        self,
        min_volume_ratio: float = 1.30,
        min_atr_percent: float = 0.30,
        max_spread_percent: float = 0.15,
    ):
        self.min_volume_ratio = min_volume_ratio
        self.min_atr_percent = min_atr_percent
        self.max_spread_percent = max_spread_percent

    # -----------------------------------------

    def volume_filter(
        self,
        volume_ratio: float,
    ) -> bool:

        return volume_ratio >= self.min_volume_ratio

    # -----------------------------------------

    def volatility_filter(
        self,
        atr_percent: float,
    ) -> bool:

        return atr_percent >= self.min_atr_percent

    # -----------------------------------------

    def spread_filter(
        self,
        spread_percent: float,
    ) -> bool:

        return spread_percent <= self.max_spread_percent

    # -----------------------------------------

    def trend_filter(
        self,
        ema20: float,
        ema50: float,
        price: float,
    ) -> bool:

        return (
            price > ema20
            and ema20 > ema50
        )

    # -----------------------------------------

    def fast_filter(
        self,
        *,
        price: float,
        ema20: float,
        ema50: float,
        volume_ratio: float,
        atr_percent: float,
        spread_percent: float,
    ) -> FilterResult:

        reasons = []

        score = 0

        if self.trend_filter(price, ema20, ema50):
            score += 30
        else:
            reasons.append("Trend Failed")

        if self.volume_filter(volume_ratio):
            score += 25
        else:
            reasons.append("Low Volume")

        if self.volatility_filter(atr_percent):
            score += 25
        else:
            reasons.append("Low Volatility")

        if self.spread_filter(spread_percent):
            score += 20
        else:
            reasons.append("High Spread")

        return FilterResult(
            passed=score >= 80,
            score=score,
            reasons=reasons,
        )
