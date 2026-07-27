import pandas as pd
import numpy as np


class IndicatorsEngine:
    """
    محرك حساب المؤشرات الفنية.
    """

    @staticmethod
    def ema(series: pd.Series, period: int):
        return series.ewm(
            span=period,
            adjust=False
        ).mean()

    @staticmethod
    def rsi(series: pd.Series, period: int = 14):

        delta = series.diff()

        gain = delta.clip(lower=0)

        loss = -delta.clip(upper=0)

        avg_gain = gain.ewm(
            alpha=1 / period,
            adjust=False
        ).mean()

        avg_loss = loss.ewm(
            alpha=1 / period,
            adjust=False
        ).mean()

        rs = avg_gain / avg_loss

        return 100 - (100 / (1 + rs))

    @staticmethod
    def atr(df: pd.DataFrame, period: int = 14):

        high = df["high"]

        low = df["low"]

        close = df["close"]

        prev_close = close.shift(1)

        tr = pd.concat(
            [
                high - low,
                (high - prev_close).abs(),
                (low - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)

        return tr.ewm(
            alpha=1 / period,
            adjust=False
        ).mean()

    @staticmethod
    def adx(df: pd.DataFrame, period: int = 14):

        high = df["high"]

        low = df["low"]

        close = df["close"]

        plus_dm = high.diff()

        minus_dm = -low.diff()

        plus_dm = plus_dm.where(
            (plus_dm > minus_dm) & (plus_dm > 0),
            0.0,
        )

        minus_dm = minus_dm.where(
            (minus_dm > plus_dm) & (minus_dm > 0),
            0.0,
        )

        tr = pd.concat(
            [
                high - low,
                (high - close.shift()).abs(),
                (low - close.shift()).abs(),
            ],
            axis=1,
        ).max(axis=1)

        atr = tr.ewm(
            alpha=1 / period,
            adjust=False,
        ).mean()

        plus_di = (
            100
            * plus_dm.ewm(
                alpha=1 / period,
                adjust=False,
            ).mean()
            / atr
        )

        minus_di = (
            100
            * minus_dm.ewm(
                alpha=1 / period,
                adjust=False,
            ).mean()
            / atr
        )

        dx = (
            (plus_di - minus_di).abs()
            / (plus_di + minus_di)
        ) * 100

        adx = dx.ewm(
            alpha=1 / period,
            adjust=False,
        ).mean()

        return adx

    @staticmethod
    def macd(
        series: pd.Series,
        fast=12,
        slow=26,
        signal=9,
    ):

        ema_fast = IndicatorsEngine.ema(
            series,
            fast,
        )

        ema_slow = IndicatorsEngine.ema(
            series,
            slow,
        )

        macd = ema_fast - ema_slow

        signal_line = macd.ewm(
            span=signal,
            adjust=False,
        ).mean()

        histogram = macd - signal_line

        return (
            macd,
            signal_line,
            histogram,
        )

    @staticmethod
    def bollinger_bands(
        series: pd.Series,
        period=20,
        std=2,
    ):

        middle = series.rolling(
            period
        ).mean()

        deviation = (
            series.rolling(period).std()
            * std
        )

        upper = middle + deviation

        lower = middle - deviation

        return (
            upper,
            middle,
            lower,
        )

    @staticmethod
    def calculate_all(df: pd.DataFrame):

        if len(df) < 120:
            return None

        df = df.copy()

        df["ema100"] = IndicatorsEngine.ema(
            df["close"],
            100,
        )

        df["rsi"] = IndicatorsEngine.rsi(
            df["close"],
            14,
        )

        df["atr"] = IndicatorsEngine.atr(
            df,
            14,
        )

        df["adx"] = IndicatorsEngine.adx(
            df,
            14,
        )

        (
            df["macd"],
            df["macd_signal"],
            df["macd_hist"],
        ) = IndicatorsEngine.macd(
            df["close"]
        )

        (
            df["bb_upper"],
            df["bb_mid"],
            df["bb_lower"],
        ) = IndicatorsEngine.bollinger_bands(
            df["close"]
        )

        return df
