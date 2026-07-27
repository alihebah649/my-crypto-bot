from pathlib import Path

code = '''"""
Professional Indicators Engine (skeleton)
"""

import pandas as pd

class IndicatorsEngine:
    @staticmethod
    def ema(series, period):
        return series.ewm(span=period, adjust=False).mean()

    @staticmethod
    def rsi(series, period=14):
        delta = series.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
        rs = avg_gain / avg_loss
        return 100 - (100/(1+rs))

    @staticmethod
    def atr(df, period=14):
        high, low, close = df["high"], df["low"], df["close"]
        prev = close.shift(1)
        tr = pd.concat([
            high-low,
            (high-prev).abs(),
            (low-prev).abs()
        ], axis=1).max(axis=1)
        return tr.ewm(alpha=1/period, adjust=False).mean()

    @staticmethod
    def adx(df, period=14):
        high, low = df["high"], df["low"]
        plus_dm = high.diff()
        minus_dm = -low.diff()
        plus_dm = plus_dm.where((plus_dm>minus_dm)&(plus_dm>0),0.0)
        minus_dm = minus_dm.where((minus_dm>plus_dm)&(minus_dm>0),0.0)
        atr = IndicatorsEngine.atr(df, period)
        plus_di = 100*plus_dm.ewm(alpha=1/period,adjust=False).mean()/atr
        minus_di = 100*minus_dm.ewm(alpha=1/period,adjust=False).mean()/atr
        dx=((plus_di-minus_di).abs()/(plus_di+minus_di))*100
        return dx.ewm(alpha=1/period, adjust=False).mean()

    @staticmethod
    def macd(series, fast=12, slow=26, signal=9):
        ef=IndicatorsEngine.ema(series,fast)
        es=IndicatorsEngine.ema(series,slow)
        m=ef-es
        s=m.ewm(span=signal, adjust=False).mean()
        return m,s,m-s

    @staticmethod
    def bollinger_bands(series, period=20, std=2):
        mid=series.rolling(period).mean()
        dev=series.rolling(period).std()*std
        return mid+dev, mid, mid-dev

    @staticmethod
    def supertrend(df, period=10, multiplier=3.0):
        atr=IndicatorsEngine.atr(df, period)
        hl2=(df["high"]+df["low"])/2
        upper=hl2+multiplier*atr
        lower=hl2-multiplier*atr
        trend=[True]*len(df)
        st=[0.0]*len(df)
        for i in range(1,len(df)):
            if df["close"].iloc[i]>upper.iloc[i-1]:
                trend[i]=True
            elif df["close"].iloc[i]<lower.iloc[i-1]:
                trend[i]=False
            else:
                trend[i]=trend[i-1]
            st[i]=lower.iloc[i] if trend[i] else upper.iloc[i]
        return pd.Series(st,index=df.index), pd.Series(trend,index=df.index)

    @staticmethod
    def calculate_all(df):
        if len(df)<120:
            return None
        df=df.copy()
        df["ema100"]=IndicatorsEngine.ema(df["close"],100)
        df["ema200"]=IndicatorsEngine.ema(df["close"],200)
        df["rsi"]=IndicatorsEngine.rsi(df["close"])
        df["atr"]=IndicatorsEngine.atr(df)
        df["adx"]=IndicatorsEngine.adx(df)
        df["macd"],df["macd_signal"],df["macd_hist"]=IndicatorsEngine.macd(df["close"])
        df["bb_upper"],df["bb_mid"],df["bb_lower"]=IndicatorsEngine.bollinger_bands(df["close"])
        df["supertrend"],df["supertrend_up"]=IndicatorsEngine.supertrend(df)
        return df
'''
path="/mnt/data/indicators_engine.py"
Path(path).write_text(code,encoding="utf-8")
print(path)
