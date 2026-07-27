import pandas as pd
import numpy as np


class IndicatorEngine:

    def __init__(self):
        pass

    # ============================================
    # EMA
    # ============================================

    def ema(self, series, period):

        return series.ewm(
            span=period,
            adjust=False
        ).mean()

    # ============================================
    # RSI
    # ============================================

    def rsi(self, close, period=14):

        delta = close.diff()

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

    # ============================================
    # ATR
    # ============================================

    def atr(self, df, period=14):

        prev_close = df["close"].shift()

        tr = pd.concat(
            [
                df["high"] - df["low"],
                (df["high"] - prev_close).abs(),
                (df["low"] - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)

        return tr.ewm(
            alpha=1 / period,
            adjust=False
        ).mean()

    # ============================================
    # Volume Ratio
    # ============================================

    def volume_ratio(self, volume, period=20):

        avg = volume.rolling(period).mean()

        return volume / avg

    # ============================================
    # ATR Percent
    # ============================================

    def atr_percent(self, atr, close):

        return atr / close * 100

    # ============================================
    # VWAP
    # ============================================

    def vwap(self, df):

        pv = (df["close"] * df["volume"]).cumsum()

        vol = df["volume"].cumsum()

        return pv / vol

    # ============================================
    # تجهيز جميع المؤشرات
    # ============================================

    def calculate(self, df):

        df = df.copy()

        df["ema20"] = self.ema(df["close"], 20)

        df["ema50"] = self.ema(df["close"], 50)

        df["ema200"] = self.ema(df["close"], 200)

        df["rsi"] = self.rsi(df["close"])

        df["atr"] = self.atr(df)

        df["atr_percent"] = self.atr_percent(
            df["atr"],
            df["close"]
        )

        df["volume_ratio"] = self.volume_ratio(
            df["volume"]
        )

        df["vwap"] = self.vwap(df)

        return df
