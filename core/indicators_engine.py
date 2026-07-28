import numpy as np
import pandas as pd


class IndicatorEngine:
    """
    Shadow Trading System V3
    Indicator Engine

    يعتمد على DataFrame يحتوي الأعمدة:

    open
    high
    low
    close
    volume
    """

    # ==========================================================
    # EMA
    # ==========================================================

    @staticmethod
    def ema(
        series,
        period,
    ):

        return series.ewm(
            span=period,
            adjust=False,
        ).mean()

    # ==========================================================
    # RSI
    # ==========================================================

    @staticmethod
    def rsi(
        close,
        period=14,
    ):

        delta = close.diff()

        gain = delta.clip(lower=0)

        loss = -delta.clip(upper=0)

        avg_gain = gain.ewm(
            alpha=1 / period,
            adjust=False,
        ).mean()

        avg_loss = loss.ewm(
            alpha=1 / period,
            adjust=False,
        ).mean()

        rs = avg_gain / avg_loss

        rsi = 100 - (
            100 / (1 + rs)
        )

        return rsi

    # ==========================================================
    # STOCHASTIC RSI
    # ==========================================================

    @staticmethod
    def stochastic_rsi(
        close,
        rsi_period=14,
        stoch_period=14,
    ):

        rsi = IndicatorEngine.rsi(
            close,
            rsi_period,
        )

        lowest = rsi.rolling(
            stoch_period,
        ).min()

        highest = rsi.rolling(
            stoch_period,
        ).max()

        denominator = (
            highest - lowest
        ).replace(
            0,
            np.nan,
        )

        stoch = (
            (
                rsi - lowest
            )
            /
            denominator
        ) * 100

        return stoch

    # ==========================================================
    # RATE OF CHANGE
    # ==========================================================

    @staticmethod
    def roc(
        close,
        period=10,
    ):

        return (
            close.pct_change(period)
        ) * 100

    # ==========================================================
    # ATR
    # ==========================================================

    @staticmethod
    def atr(
        df,
        period=14,
    ):

        previous_close = (
            df["close"].shift(1)
        )

        tr = pd.concat(

            [

                df["high"] - df["low"],

                (
                    df["high"]
                    - previous_close
                ).abs(),

                (
                    df["low"]
                    - previous_close
                ).abs(),

            ],

            axis=1,

        ).max(axis=1)

        atr = tr.ewm(

            alpha=1 / period,

            adjust=False,

        ).mean()

        return atr

    # ==========================================================
    # MACD
    # ==========================================================

    @staticmethod
    def macd(
        close,
    ):

        ema12 = IndicatorEngine.ema(
            close,
            12,
        )

        ema26 = IndicatorEngine.ema(
            close,
            26,
        )

        macd = ema12 - ema26

        signal = macd.ewm(
            span=9,
            adjust=False,
        ).mean()

        histogram = (
            macd - signal
        )

        return (

            macd,

            signal,

            histogram,

        )

    # ==========================================================
    # BOLLINGER BANDS
    # ==========================================================

    @staticmethod
    def bollinger(
        close,
        period=20,
        std=2,
    ):

        middle = close.rolling(
            period,
        ).mean()

        sigma = close.rolling(
            period,
        ).std()

        upper = (
            middle
            + sigma * std
        )

        lower = (
            middle
            - sigma * std
        )

        return (

            upper,

            middle,

            lower,

        )

    # ==========================================================
    # ADX
    # ==========================================================

    @staticmethod
    def adx(
        df,
        period=14,
    ):

        high = df["high"]
        low = df["low"]
        close = df["close"]

        plus_dm = high.diff()

        minus_dm = -low.diff()

        plus_dm = plus_dm.where(
            (plus_dm > minus_dm)
            & (plus_dm > 0),
            0.0,
        )

        minus_dm = minus_dm.where(
            (minus_dm > plus_dm)
            & (minus_dm > 0),
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

        atr = tr.rolling(period).mean()

        plus_di = (

            100

            * plus_dm.rolling(period).mean()

            / atr

        )

        minus_di = (

            100

            * minus_dm.rolling(period).mean()

            / atr

        )

        denominator = (

            plus_di + minus_di

        ).replace(

            0,

            np.nan,

        )

        dx = (

            (plus_di - minus_di).abs()

            /

            denominator

        ) * 100

        return dx.rolling(period).mean()

    # ==========================================================
    # VWAP
    # ==========================================================

    @staticmethod
    def vwap(
        df,
    ):

        typical_price = (

            df["high"]

            + df["low"]

            + df["close"]

        ) / 3

        return (

            (
                typical_price
                * df["volume"]
            ).cumsum()

            /

            df["volume"].cumsum()

        )

    # ==========================================================
    # Relative Volume
    # ==========================================================

    @staticmethod
    def relative_volume(
        volume,
        period=20,
    ):

        average = volume.rolling(
            period
        ).mean()

        return volume / average

    # ==========================================================
    # Donchian Channel
    # ==========================================================

    @staticmethod
    def donchian(
        df,
        period=20,
    ):

        upper = (

            df["high"]

            .rolling(period)

            .max()

        )

        lower = (

            df["low"]

            .rolling(period)

            .min()

        )

        middle = (

            upper + lower

        ) / 2

        return (

            upper,

            middle,

            lower,

        )

    # ==========================================================
    # SuperTrend
    # ==========================================================

    @staticmethod
    def supertrend(
        df,
        period=10,
        multiplier=3.0,
    ):

        atr = IndicatorEngine.atr(
            df,
            period,
        )

        hl2 = (

            df["high"]

            + df["low"]

        ) / 2

        upperband = (
            hl2 + multiplier * atr
        ).copy()

        lowerband = (
            hl2 - multiplier * atr
        ).copy()

        trend = [True]

        supertrend = [

            lowerband.iloc[0]

        ]

        for i in range(

            1,

            len(df),

        ):

            if (

                df["close"].iloc[i]

                >

                upperband.iloc[i - 1]

            ):

                trend.append(True)

            elif (

                df["close"].iloc[i]

                <

                lowerband.iloc[i - 1]

            ):

                trend.append(False)

            else:

                trend.append(

                    trend[-1]

                )

                if trend[-1]:

                    lowerband.iloc[i] = max(

                        lowerband.iloc[i],

                        lowerband.iloc[i - 1],

                    )

                else:

                    upperband.iloc[i] = min(

                        upperband.iloc[i],

                        upperband.iloc[i - 1],

                    )

            if trend[-1]:

                supertrend.append(

                    lowerband.iloc[i]

                )

            else:

                supertrend.append(

                    upperband.iloc[i]

                )

        return (

            pd.Series(

                supertrend,

                index=df.index,

            ),

            pd.Series(

                trend,

                index=df.index,

            ),

        )


``
