from dataclasses import dataclass
from typing import List


@dataclass
class Signal:
    symbol: str
    side: str            # BUY / SELL
    score: float
    reasons: List[str]
    price: float
    atr: float = 0.0


class SignalEngine:
    """
    محرك الإشارات.

    حالياً هو مجرد Container للإشارات.
    لاحقاً سنضيف إليه:
        - EMA
        - RSI
        - Bollinger
        - Volume
        - Candlestick
        - Market Regime
        - Correlation
    """

    def __init__(self):
        self.signals = []

    def create_buy_signal(
        self,
        symbol,
        score,
        reasons,
        price,
        atr
    ):
        signal = Signal(
            symbol=symbol,
            side="BUY",
            score=score,
            reasons=reasons,
            price=price,
            atr=atr
        )

        self.signals.append(signal)
        return signal

    def create_sell_signal(
        self,
        symbol,
        score,
        reasons,
        price
    ):
        signal = Signal(
            symbol=symbol,
            side="SELL",
            score=score,
            reasons=reasons,
            price=price
        )

        self.signals.append(signal)
        return signal

    def clear(self):
        self.signals.clear()

    def get_all(self):
        return list(self.signals)
