"""Dual-lane strategy: 5m reversal-led Scalping + high-confidence Swing."""
from __future__ import annotations
import pandas as pd

# Scalping is intentionally easier to trigger than Swing, but still requires
# strong 5m evidence plus macro support and minimum liquidity.
SCALP_SCORE_THRESHOLD = 65
SWING_SCORE_THRESHOLD = 80
BUY_SCORE_THRESHOLD = SWING_SCORE_THRESHOLD
SCALP_MIN_VOLUME_RATIO = 0.75
SCALP_MAX_RSI = 60.0


def calculate_ema(prices,period=100):
    if len(prices)<period:return 0.0
    return float(pd.Series(prices,dtype="float64").ewm(span=period,adjust=False).mean().iloc[-1])


def calculate_rsi(prices,period=14):
    if len(prices)<period+1:return 0.0
    s=pd.Series(prices,dtype="float64");d=s.diff();g=d.clip(lower=0);l=-d.clip(upper=0);ag=g.ewm(alpha=1/period,adjust=False).mean();al=l.ewm(alpha=1/period,adjust=False).mean()
    if float(al.iloc[-1])==0:return 100.0 if float(ag.iloc[-1])>0 else 50.0
    return float((100-100/(1+ag/al)).iloc[-1])


def calculate_atr(candles,period=14):
    if len(candles)<period+1:return 0.0
    h=pd.Series([x["high"]for x in candles]);l=pd.Series([x["low"]for x in candles]);c=pd.Series([x["close"]for x in candles]);p=c.shift(1);tr=pd.concat([h-l,(h-p).abs(),(l-p).abs()],axis=1).max(axis=1);return float(tr.ewm(alpha=1/period,adjust=False).mean().iloc[-1])


def calculate_bollinger(candles,period=20,deviations=2.0):
    if len(candles)<period:return 0.0,0.0,0.0
    s=pd.Series([x["close"]for x in candles]);m=float(s.rolling(period).mean().iloc[-1]);d=float(s.rolling(period).std(ddof=0).iloc[-1]);return m-deviations*d,m,m+deviations*d


def bullish_pattern(candles):
    if len(candles)<4:return False,"INSUFFICIENT_CANDLES",False
    a,b,d=candles[-1],candles[-2],candles[-3];ba=abs(a["close"]-a["open"]);bb=abs(b["close"]-b["open"]);bd=abs(d["close"]-d["open"]);bull=a["close"]>a["open"];bbull=b["close"]>b["open"];bearb=b["close"]<b["open"];beard=d["close"]<d["open"];ls=min(a["open"],a["close"])-a["low"];us=a["high"]-max(a["open"],a["close"]);name=""
    if beard and bbull and b["close"]>=d["open"] and b["open"]<=d["close"] and bb>bd:name="BULLISH_OUTSIDE"
    elif beard and bb<=bd*.30 and bull and b["low"]<d["low"] and b["low"]<a["low"]:name="MORNING_STAR"
    elif bearb and bull and a["close"]>=b["open"] and a["open"]<=b["close"] and ba>bb:name="BULLISH_ENGULFING"
    elif ls>=2*ba and us<.4*max(ba,1e-12) and ba>0:name="HAMMER"
    elif bull and bbull and a["close"]>b["high"]:name="BULLISH_BREAKOUT"
    if not name:return False,"NEUTRAL",False
    return True,name,bool(bull and a["close"]>b["high"])


def _volume_ratio(candles,window=20):
    if len(candles)<window+1:return 0.0
    avg=sum(x["volume"]for x in candles[-window-1:-1])/float(window);return candles[-1]["volume"]/avg if avg>0 else 0.0


def _macro_support(price,lower,middle):
    if lower<=0:return 0,""
    distance=(price-lower)/price if price>0 else 999
    if price<=lower:return 15,"15M_BOLLINGER_LOWER_SUPPORT"
    if distance<=.005:return 12,"15M_BOLLINGER_NEAR_SUPPORT"
    if price<=middle:return 6,"15M_BOLLINGER_LOWER_HALF"
    return 0,""


def score_symbol(symbol,ticker,candles_15m,candles_5m):
    c15=candles_15m[:-1] if len(candles_15m)>1 else [];c5=candles_5m[:-1] if len(candles_5m)>1 else [];price=float(ticker.get("lastPrice",0))
    if len(c15)<100 or len(c5)<4 or price<=0:return {"symbol":symbol,"score":0,"signal":"HOLD","swing_score":0,"scalp_score":0,"swing_signal":"HOLD","scalp_signal":"HOLD","trade_mode":"NONE","reasons":["INSUFFICIENT_DATA"],"price":price,"ema100":0.0,"rsi":0.0,"rsi5m":0.0,"atr":0.0}
    p15=[x["close"]for x in c15];p5=[x["close"]for x in c5];ema100=calculate_ema(p15);r15=calculate_rsi(p15);r5=calculate_rsi(p5);atr=calculate_atr(c15);atr5=calculate_atr(c5);lo15,mid15,up15=calculate_bollinger(c15);lo5,mid5,up5=calculate_bollinger(c5);v15=_volume_ratio(c15);v5=_volume_ratio(c5);found,name,confirmed=bullish_pattern(c5)
    swing=0;swing_reasons=[]
    if price>ema100:swing+=20;swing_reasons.append("EMA100_TREND")
    if r15<=30:swing+=20;swing_reasons.append("RSI_DEEP_OVERSOLD")
    elif r15<40:swing+=15;swing_reasons.append("RSI_OVERSOLD")
    elif r15<50:swing+=8;swing_reasons.append("RSI_RECOVERY_ZONE")
    if lo15>0:
        dist=(price-lo15)/price
        if price<=lo15:swing+=25;swing_reasons.append("BOLLINGER_LOWER_SUPPORT")
        elif dist<=.005:swing+=18;swing_reasons.append("BOLLINGER_NEAR_SUPPORT")
        elif price<=mid15:swing+=8;swing_reasons.append("BOLLINGER_LOWER_HALF")
    if v15>=1.20:swing+=15;swing_reasons.append("VOLUME_CONFIRMATION")
    elif v15>=1.05:swing+=8;swing_reasons.append("VOLUME_RISING")
    if found and confirmed:swing+=20;swing_reasons.append(f"5M_{name}_CONFIRMED")
    elif found:swing+=8;swing_reasons.append(f"5M_{name}")
    swing=min(swing,100)
    macro_points,macro_reason=_macro_support(price,lo15,mid15);scalp=macro_points;scalp_reasons=[macro_reason] if macro_reason else []
    if r5<=25:scalp+=20;scalp_reasons.append("5M_RSI_DEEP_OVERSOLD")
    elif r5<=35:scalp+=16;scalp_reasons.append("5M_RSI_OVERSOLD")
    elif r5<=45:scalp+=10;scalp_reasons.append("5M_RSI_RECOVERY_ZONE")
    if lo5>0:
        dist=(price-lo5)/price
        if price<=lo5:scalp+=20;scalp_reasons.append("5M_BOLLINGER_LOWER_SUPPORT")
        elif dist<=.005:scalp+=16;scalp_reasons.append("5M_BOLLINGER_NEAR_SUPPORT")
        elif price<=mid5:scalp+=8;scalp_reasons.append("5M_BOLLINGER_LOWER_HALF")
    if v5>=1.20:scalp+=15;scalp_reasons.append("5M_VOLUME_CONFIRMATION")
    elif v5>=1.05:scalp+=8;scalp_reasons.append("5M_VOLUME_RISING")
    elif v5>=SCALP_MIN_VOLUME_RATIO:scalp+=3;scalp_reasons.append("5M_VOLUME_ACCEPTABLE")
    if found and confirmed:scalp+=30;scalp_reasons.append(f"5M_{name}_CONFIRMED")
    elif found:scalp+=8;scalp_reasons.append(f"5M_{name}")
    scalp=min(scalp,100)

    # Two valid Scalp entry paths:
    # 1) Confirmed 5m bullish reversal/breakout with macro support.
    # 2) High-confidence recovery: score threshold reached from independent
    #    support/oversold/liquidity evidence, without requiring a candle label.
    confirmed_reversal=bool(found and confirmed)
    high_confidence_recovery=bool(
        scalp>=SCALP_SCORE_THRESHOLD
        and r5<=45.0
        and v5>=SCALP_MIN_VOLUME_RATIO
    )
    gate=bool(
        macro_points>0
        and r5<=SCALP_MAX_RSI
        and v5>=SCALP_MIN_VOLUME_RATIO
        and (confirmed_reversal or high_confidence_recovery)
    )
    gate_reasons=[]
    if macro_points<=0:gate_reasons.append("NO_15M_MACRO_SUPPORT")
    if r5>SCALP_MAX_RSI:gate_reasons.append("5M_RSI_TOO_HIGH")
    if v5<SCALP_MIN_VOLUME_RATIO:gate_reasons.append("5M_VOLUME_TOO_LOW")
    if confirmed_reversal:gate_reasons.append("CONFIRMED_5M_REVERSAL")
    elif high_confidence_recovery:gate_reasons.append("HIGH_CONFIDENCE_RECOVERY")
    else:gate_reasons.append("NO_CONFIRMED_REVERSAL_OR_RECOVERY_SCORE")

    scalp_signal="BUY" if scalp>=SCALP_SCORE_THRESHOLD and gate else "HOLD";swing_signal="BUY" if swing>=SWING_SCORE_THRESHOLD else "HOLD"
    if scalp_signal=="BUY":mode="SCALP";selected=scalp;reasons=scalp_reasons
    elif swing_signal=="BUY":mode="SWING";selected=swing;reasons=swing_reasons
    else:mode="NONE";selected=max(scalp,swing);reasons=scalp_reasons if scalp>=swing else swing_reasons
    return {"symbol":symbol,"score":selected,"signal":"BUY" if mode!="NONE" else "HOLD","trade_mode":mode,"swing_score":swing,"scalp_score":scalp,"swing_signal":swing_signal,"scalp_signal":scalp_signal,"scalp_gate":gate,"scalp_gate_reasons":gate_reasons,"scalp_confirmed_reversal":confirmed_reversal,"scalp_high_confidence_recovery":high_confidence_recovery,"scalp_min_volume_ratio":SCALP_MIN_VOLUME_RATIO,"scalp_max_rsi":SCALP_MAX_RSI,"reasons":reasons,"swing_reasons":swing_reasons,"scalp_reasons":scalp_reasons,"price":price,"ema100":ema100,"rsi":r15,"rsi5m":r5,"atr":atr,"atr5m":atr5,"lower_band":lo15,"middle_band":mid15,"upper_band":up15,"lower_band_5m":lo5,"middle_band_5m":mid5,"upper_band_5m":up5,"volume_ratio":v15,"volume_ratio_5m":v5,"pattern":name,"pattern_confirmed":confirmed}
