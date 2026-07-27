from dataclasses import dataclass

import pandas as pd


@dataclass
class MarketState:
    regime: str
    trend_strength: float
    volatility: float
    allow_buy: bool
    allow_sell: bool


class MarketRegimeEngine:
    """
    مسؤول عن تحديد حالة السوق.
    """

    def __init__(self):

        self.adx_threshold = 25

        self.high_volatility = 0.05

    def detect(self, df: pd.DataFrame) -> MarketState:

        if df is None or len(df) < 100:

            return MarketState(
                regime="UNKNOWN",
                trend_strength=0.0,
                volatility=0.0,
                allow_buy=False,
                allow_sell=False,
            )

        last = df.iloc[-1]

        close = last["close"]

        ema100 = last["ema100"]

        atr = last["atr"]

        adx = last.get("adx", 0)

        volatility = atr / close if close else 0

        # -----------------------------------
        # تحديد الاتجاه العام
        # -----------------------------------

        if close > ema100:

            regime = "BULL"

        elif close < ema100:

            regime = "BEAR"

        else:

            regime = "SIDEWAYS"

        # -----------------------------------
        # قوة الاتجاه
        # -----------------------------------

        trend_strength = float(adx)

        # -----------------------------------
        # السوق العرضي
        # -----------------------------------

        if trend_strength < self.adx_threshold:

            regime = "SIDEWAYS"

        # -----------------------------------
        # تقلب مرتفع جداً
        # -----------------------------------

        if volatility >= self.high_volatility:

            regime = "HIGH_VOLATILITY"

        # -----------------------------------
        # السماح بالشراء
        # -----------------------------------

        allow_buy = regime in [
            "BULL",
        ]

        # -----------------------------------
        # السماح بالبيع
        # -----------------------------------

        allow_sell = regime in [
            "BEAR",
            "HIGH_VOLATILITY",
        ]

        return MarketState(
            regime=regime,
            trend_strength=trend_strength,
            volatility=volatility,
            allow_buy=allow_buy,
            allow_sell=allow_sell,
        )
