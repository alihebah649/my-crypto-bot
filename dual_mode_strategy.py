"""Dual-lane strategy: 5m reversal-led Scalping + high-confidence Swing."""
from __future__ import annotations

import time

import pandas as pd

from multi_timeframe_context import analyze_multi_timeframe_context

# Scalp and Swing remain separate lanes. The scalp threshold stays at 65;
# however, a context score alone is not an entry trigger anymore.
SCALP_SCORE_THRESHOLD = 65
SWING_SCORE_THRESHOLD = 80
BUY_SCORE_THRESHOLD = SWING_SCORE_THRESHOLD
SCALP_MIN_VOLUME_RATIO = 0.75
SCALP_MAX_RSI = 55.0
SCALP_RSI_RISE_MIN = 1.5
SCALP_RECOVERY_TRIGGER_MIN = 2
SCALP_RECOVERY_POINTS = 4
# SCALP score is deliberately calibrated by evidence families rather than
# allowing correlated support/RSI/Bollinger signals to stack into false
# confidence. The public threshold remains exactly 65.
SCALP_REVERSION_FAMILY_MAX = 22
SCALP_PATTERN_POINTS_MAX = 20
SCALP_STRUCTURAL_BONUS = 4


def _closed_candles(candles, captured_at=None):
    """Use the latest candle when it is closed; otherwise exclude the open candle."""
    if not candles:
        return []
    latest = candles[-1]
    latest_close = latest.get("close_time") if isinstance(latest, dict) else None
    if latest_close is not None:
        try:
            now_ms = float(captured_at if captured_at is not None else time.time()) * 1000.0
            if now_ms > float(latest_close):
                return list(candles)
        except (TypeError, ValueError):
            pass
    return list(candles[:-1]) if len(candles) > 1 else []


def calculate_ema(prices, period=100):
    if len(prices) < period:
        return 0.0
    return float(pd.Series(prices, dtype="float64").ewm(span=period, adjust=False).mean().iloc[-1])


def calculate_rsi(prices, period=14):
    if len(prices) < period + 1:
        return 0.0
    s = pd.Series(prices, dtype="float64")
    d = s.diff()
    g = d.clip(lower=0)
    l = -d.clip(upper=0)
    ag = g.ewm(alpha=1 / period, adjust=False).mean()
    al = l.ewm(alpha=1 / period, adjust=False).mean()
    if float(al.iloc[-1]) == 0:
        return 100.0 if float(ag.iloc[-1]) > 0 else 50.0
    return float((100 - 100 / (1 + ag / al)).iloc[-1])


def calculate_atr(candles, period=14):
    if len(candles) < period + 1:
        return 0.0
    h = pd.Series([x["high"] for x in candles])
    l = pd.Series([x["low"] for x in candles])
    c = pd.Series([x["close"] for x in candles])
    p = c.shift(1)
    tr = pd.concat([h - l, (h - p).abs(), (l - p).abs()], axis=1).max(axis=1)
    return float(tr.ewm(alpha=1 / period, adjust=False).mean().iloc[-1])


def calculate_bollinger(candles, period=20, deviations=2.0):
    if len(candles) < period:
        return 0.0, 0.0, 0.0
    s = pd.Series([x["close"] for x in candles])
    m = float(s.rolling(period).mean().iloc[-1])
    d = float(s.rolling(period).std(ddof=0).iloc[-1])
    return m - deviations * d, m, m + deviations * d


def bullish_pattern(candles):
    if len(candles) < 4:
        return False, "INSUFFICIENT_CANDLES", False
    a, b, d = candles[-1], candles[-2], candles[-3]
    ba = abs(a["close"] - a["open"])
    bb = abs(b["close"] - b["open"])
    bd = abs(d["close"] - d["open"])
    bull = a["close"] > a["open"]
    bbull = b["close"] > b["open"]
    bearb = b["close"] < b["open"]
    beard = d["close"] < d["open"]
    ls = min(a["open"], a["close"]) - a["low"]
    us = a["high"] - max(a["open"], a["close"])
    name = ""
    if beard and bbull and b["close"] >= d["open"] and b["open"] <= d["close"] and bb > bd:
        name = "BULLISH_OUTSIDE"
    elif beard and bb <= bd * 0.30 and bull and b["low"] < d["low"] and b["low"] < a["low"]:
        name = "MORNING_STAR"
    elif bearb and bull and a["close"] >= b["open"] and a["open"] <= b["close"] and ba > bb:
        name = "BULLISH_ENGULFING"
    elif ls >= 2 * ba and us < 0.4 * max(ba, 1e-12) and ba > 0:
        name = "HAMMER"
    elif bull and bbull and a["close"] > b["high"]:
        name = "BULLISH_BREAKOUT"
    if not name:
        return False, "NEUTRAL", False
    return True, name, bool(bull and a["close"] > b["high"])


def _volume_ratio(candles, window=20):
    if len(candles) < window + 1:
        return 0.0
    avg = sum(x["volume"] for x in candles[-window - 1:-1]) / float(window)
    return candles[-1]["volume"] / avg if avg > 0 else 0.0


def _macro_support(price, lower, middle):
    if lower <= 0:
        return 0, ""
    distance = (price - lower) / price if price > 0 else 999
    if price <= lower:
        return 15, "15M_BOLLINGER_LOWER_SUPPORT"
    if distance <= 0.005:
        return 12, "15M_BOLLINGER_NEAR_SUPPORT"
    if price <= middle:
        return 6, "15M_BOLLINGER_LOWER_HALF"
    return 0, ""


def _scalp_recovery_confirmation(candles, current_rsi):
    """Confirm that a 5m oversold/support candidate is actually recovering."""
    if len(candles) < 2:
        return False, 0, []

    previous = candles[-2]
    current = candles[-1]
    previous_rsi = calculate_rsi([x["close"] for x in candles[:-1]])

    rsi_rising = (float(current_rsi) - float(previous_rsi)) >= SCALP_RSI_RISE_MIN
    price_rising = float(current["close"]) > float(previous["close"])
    bullish_body = float(current["close"]) > float(current["open"])

    checks = [rsi_rising, price_rising, bullish_body]
    count = sum(bool(x) for x in checks)
    reasons = []
    if rsi_rising:
        reasons.append("5M_RSI_RISING")
    if price_rising:
        reasons.append("5M_PRICE_RECOVERY")
    if bullish_body:
        reasons.append("5M_BULLISH_BODY")

    return count >= SCALP_RECOVERY_TRIGGER_MIN, count, reasons


def _scalp_structural_confirmation(candles_5m, candles_15m, mtf, *, confirmed_reversal, seller_failure_confirmed):
    """Require multi-candle structure before a 5m bounce becomes a SCALP entry.

    A single bullish candle can be a dead-cat bounce. Structural evidence is
    intentionally narrow: a higher-low on 5m/15m, a confirmed 5m reclaim with
    seller-failure while the 15m frame is not bearish, or a two-candle reclaim
    above the prior two-bar highs in a non-bearish 5m/15m context.
    """
    frames = mtf.get("frames", {}) if isinstance(mtf, dict) else {}
    frame5 = frames.get("5m", {}) or {}
    frame15 = frames.get("15m", {}) or {}
    patterns5 = {str(x).upper() for x in frame5.get("patterns", [])}
    patterns15 = {str(x).upper() for x in frame15.get("patterns", [])}
    higher_low = (
        "7C_HIGHER_LOW_STRUCTURE" in patterns5
        or "7C_HIGHER_LOW_STRUCTURE" in patterns15
    )
    five_bias = str(frame5.get("bias", "UNKNOWN")).upper()
    fifteen_bias = str(frame15.get("bias", "UNKNOWN")).upper()
    two_candle_reclaim = False
    if len(candles_5m) >= 3:
        current = candles_5m[-1]
        previous = candles_5m[-2]
        previous2 = candles_5m[-3]
        two_candle_reclaim = bool(
            float(current.get("close", 0.0)) > max(
                float(previous.get("high", 0.0)),
                float(previous2.get("high", 0.0)),
            )
            and float(current.get("close", 0.0)) > float(current.get("open", 0.0))
            and float(previous.get("close", 0.0)) >= float(previous2.get("close", 0.0))
        )

    non_bearish_setup = fifteen_bias in {"BULLISH", "NEUTRAL", "UNKNOWN"}
    reclaim_with_seller_failure = bool(
        confirmed_reversal
        and seller_failure_confirmed
        and five_bias == "BULLISH"
        and non_bearish_setup
    )
    structural = bool(
        (confirmed_reversal and higher_low)
        or reclaim_with_seller_failure
        or (two_candle_reclaim and five_bias == "BULLISH" and non_bearish_setup)
    )
    return {
        "confirmed": structural,
        "higher_low": higher_low,
        "two_candle_reclaim": two_candle_reclaim,
        "seller_failure": bool(seller_failure_confirmed),
        "five_m_bias": five_bias,
        "fifteen_m_bias": fifteen_bias,
        "higher_low_timeframes": tuple(
            timeframe
            for timeframe, patterns in (("5m", patterns5), ("15m", patterns15))
            if "7C_HIGHER_LOW_STRUCTURE" in patterns
        ),
    }


def score_symbol(symbol, ticker, candles_15m, candles_5m, candles_1h=None, candles_4h=None):
    """Score one symbol while preserving the original four-argument contract.

    5m remains the scalp trigger. 15m remains the setup timeframe. 1h and 4h
    are context only and can penalize a weak counter-trend recovery, but they
    cannot by themselves authorize an entry.
    """
    c15 = _closed_candles(candles_15m)
    c5 = _closed_candles(candles_5m)
    c1h = _closed_candles(candles_1h) if candles_1h else []
    c4h = _closed_candles(candles_4h) if candles_4h else []
    price = float(ticker.get("lastPrice", 0))
    if len(c15) < 100 or len(c5) < 4 or price <= 0:
        return {
            "symbol": symbol,
            "score": 0,
            "signal": "HOLD",
            "swing_score": 0,
            "scalp_score": 0,
            "swing_signal": "HOLD",
            "scalp_signal": "HOLD",
            "trade_mode": "NONE",
            "reasons": ["INSUFFICIENT_DATA"],
            "price": price,
            "ema100": 0.0,
            "rsi": 0.0,
            "rsi5m": 0.0,
            "atr": 0.0,
        }

    p15 = [x["close"] for x in c15]
    p5 = [x["close"] for x in c5]
    ema100 = calculate_ema(p15)
    r15 = calculate_rsi(p15)
    r5 = calculate_rsi(p5)
    atr = calculate_atr(c15)
    atr5 = calculate_atr(c5)
    lo15, mid15, up15 = calculate_bollinger(c15)
    lo5, mid5, up5 = calculate_bollinger(c5)
    v15 = _volume_ratio(c15)
    v5 = _volume_ratio(c5)
    found, name, confirmed = bullish_pattern(c5)

    mtf = analyze_multi_timeframe_context({"5m": c5, "15m": c15, "1h": c1h, "4h": c4h})
    mtf_frames = mtf.get("frames", {})
    mtf_bearish = bool(mtf.get("weak_countertrend_recovery"))
    mtf_bullish = bool(mtf.get("aligned_bullish"))
    # A 5m bullish pattern must not override a fully bearish 15m/1h/4h stack.
    # This keeps SCALP as a 5m lane while preventing a single short-term candle
    # from authorizing a countertrend entry during a confirmed higher-timeframe
    # downtrend.
    mtf_strong_bearish_stack = bool(
        mtf.get("higher_timeframes_bearish")
        and str(mtf_frames.get("15m", {}).get("bias", "UNKNOWN")).upper() == "BEARISH"
    )

    # Structural seller-failure is an existing multi-candle fact, not a new
    # scoring rule. Expose it to the guarded Brain using the same 5m/15m
    # patterns already used by Entry v2, so the Brain receives the field its
    # BEAR/SCALP safety contract already requires.
    seller_failure_patterns = {
        "5C_SELLING_PRESSURE_WEAKENING",
        "FOUR_C_BEAR_TO_BULL_REVERSAL",
        "8C_SELL_OFF_TO_RECOVERY",
    }
    seller_failure_confirmed = any(
        pattern in mtf_frames.get(timeframe, {}).get("patterns", [])
        for timeframe in ("5m", "15m")
        for pattern in seller_failure_patterns
    )

    # --- Swing lane (unchanged threshold semantics) -----------------------
    swing = 0
    swing_reasons = []
    if price > ema100:
        swing += 20
        swing_reasons.append("EMA100_TREND")
    if r15 <= 30:
        swing += 20
        swing_reasons.append("RSI_DEEP_OVERSOLD")
    elif r15 < 40:
        swing += 15
        swing_reasons.append("RSI_OVERSOLD")
    elif r15 < 50:
        swing += 8
        swing_reasons.append("RSI_RECOVERY_ZONE")
    if lo15 > 0:
        dist = (price - lo15) / price
        if price <= lo15:
            swing += 25
            swing_reasons.append("BOLLINGER_LOWER_SUPPORT")
        elif dist <= 0.005:
            swing += 18
            swing_reasons.append("BOLLINGER_NEAR_SUPPORT")
        elif price <= mid15:
            swing += 8
            swing_reasons.append("BOLLINGER_LOWER_HALF")
    if v15 >= 1.20:
        swing += 15
        swing_reasons.append("VOLUME_CONFIRMATION")
    elif v15 >= 1.05:
        swing += 8
        swing_reasons.append("VOLUME_RISING")
    if found and confirmed:
        swing += 20
        swing_reasons.append(f"5M_{name}_CONFIRMED")
    elif found:
        swing += 8
        swing_reasons.append(f"5M_{name}")
    if mtf_bullish:
        swing += 4
        swing_reasons.append("MTF_HIGHER_TIMEFRAME_ALIGNMENT")
    swing = min(swing, 100)

    # --- Scalp lane: independent evidence families ------------------------
    macro_points, macro_reason = _macro_support(price, lo15, mid15)
    scalp_reasons = [macro_reason] if macro_reason else []
    if r5 <= 25:
        rsi_points = 20
        scalp_reasons.append("5M_RSI_DEEP_OVERSOLD")
    elif r5 <= 35:
        rsi_points = 16
        scalp_reasons.append("5M_RSI_OVERSOLD")
    elif r5 <= 45:
        rsi_points = 10
        scalp_reasons.append("5M_RSI_RECOVERY_ZONE")
    else:
        rsi_points = 0

    bb5_points = 0
    if lo5 > 0:
        dist = (price - lo5) / price
        if price <= lo5:
            bb5_points = 20
            scalp_reasons.append("5M_BOLLINGER_LOWER_SUPPORT")
        elif dist <= 0.005:
            bb5_points = 16
            scalp_reasons.append("5M_BOLLINGER_NEAR_SUPPORT")
        elif price <= mid5:
            bb5_points = 8
            scalp_reasons.append("5M_BOLLINGER_LOWER_HALF")

    if v5 >= 1.20:
        volume_points = 15
        scalp_reasons.append("5M_VOLUME_CONFIRMATION")
    elif v5 >= 1.05:
        volume_points = 8
        scalp_reasons.append("5M_VOLUME_RISING")
    elif v5 >= SCALP_MIN_VOLUME_RATIO:
        volume_points = 3
        scalp_reasons.append("5M_VOLUME_ACCEPTABLE")
    else:
        volume_points = 0

    if found and confirmed:
        pattern_points = SCALP_PATTERN_POINTS_MAX
        scalp_reasons.append(f"5M_{name}_CONFIRMED")
    elif found:
        pattern_points = 8
        scalp_reasons.append(f"5M_{name}")
    else:
        pattern_points = 0

    recovery_confirmation, recovery_trigger_count, recovery_trigger_reasons = _scalp_recovery_confirmation(c5, r5)
    if recovery_confirmation:
        scalp_reasons.append(f"5M_RECOVERY_CONFIRMATION_+{SCALP_RECOVERY_POINTS}")

    structural = _scalp_structural_confirmation(
        c5,
        c15,
        mtf,
        confirmed_reversal=bool(found and confirmed),
        seller_failure_confirmed=seller_failure_confirmed,
    )

    # 15m/5m location, Bollinger position, and RSI are strongly correlated
    # descriptions of the same mean-reversion setup. Cap the whole family so
    # it cannot manufacture a 90+ score without independent evidence.
    reversion_raw = max(macro_points, bb5_points) + rsi_points
    reversion_points = min(SCALP_REVERSION_FAMILY_MAX, reversion_raw)
    scalp = reversion_points + volume_points + pattern_points
    if recovery_confirmation:
        scalp += SCALP_RECOVERY_POINTS
    if structural["confirmed"]:
        scalp += SCALP_STRUCTURAL_BONUS
        scalp_reasons.append("SCALP_STRUCTURAL_CONFIRMATION")
    if mtf_bullish:
        scalp += 4
        scalp_reasons.append("MTF_HIGHER_TIMEFRAME_ALIGNMENT")
    elif mtf_bearish:
        scalp -= 8
        scalp_reasons.append("MTF_COUNTERTREND_WARNING")
    scalp = max(0, min(scalp, 100))

    # Raw score remains diagnostic so historical comparisons can distinguish
    # score-calibration effects from the actual entry-quality score.
    scalp_raw = macro_points + rsi_points + bb5_points + volume_points + pattern_points
    if recovery_confirmation:
        scalp_raw += SCALP_RECOVERY_POINTS
    if structural["confirmed"]:
        scalp_raw += SCALP_STRUCTURAL_BONUS
    if mtf_bullish:
        scalp_raw += 4
    elif mtf_bearish:
        scalp_raw -= 8
    scalp_raw = max(0, min(scalp_raw, 100))

    confirmed_reversal = bool(found and confirmed)
    high_confidence_recovery = bool(
        scalp >= SCALP_SCORE_THRESHOLD
        and r5 <= 45.0
        and v5 >= SCALP_MIN_VOLUME_RATIO
        and recovery_confirmation
        and structural["confirmed"]
        and not mtf_bearish
    )

    mtf_countertrend_veto = bool(mtf_strong_bearish_stack)
    gate = bool(
        macro_points > 0
        and r5 <= SCALP_MAX_RSI
        and v5 >= SCALP_MIN_VOLUME_RATIO
        and (confirmed_reversal or recovery_confirmation)
        and structural["confirmed"]
        and not mtf_countertrend_veto
    )

    gate_reasons = []
    if macro_points <= 0:
        gate_reasons.append("NO_15M_MACRO_SUPPORT")
    if r5 > SCALP_MAX_RSI:
        gate_reasons.append("5M_RSI_TOO_HIGH")
    if v5 < SCALP_MIN_VOLUME_RATIO:
        gate_reasons.append("5M_VOLUME_TOO_LOW")
    if mtf_countertrend_veto:
        gate_reasons.append("MTF_STRONG_COUNTERTREND_VETO")
    elif mtf_bullish:
        gate_reasons.append("MTF_HIGHER_TIMEFRAME_ALIGNMENT")
    if confirmed_reversal:
        gate_reasons.append("CONFIRMED_5M_REVERSAL")
    elif recovery_confirmation:
        gate_reasons.append("CONFIRMED_5M_RECOVERY")
        gate_reasons.extend(recovery_trigger_reasons)
    else:
        gate_reasons.append("SCALP_CONTEXT_ONLY_NO_RECOVERY_TRIGGER")
    if not structural["confirmed"]:
        gate_reasons.append("SCALP_STRUCTURE_NOT_CONFIRMED")

    scalp_signal = "BUY" if scalp >= SCALP_SCORE_THRESHOLD and gate else "HOLD"
    swing_signal = "BUY" if swing >= SWING_SCORE_THRESHOLD else "HOLD"

    if scalp_signal == "BUY":
        mode = "SCALP"
        selected = scalp
        reasons = scalp_reasons + recovery_trigger_reasons if recovery_confirmation and not confirmed_reversal else scalp_reasons
    elif swing_signal == "BUY":
        mode = "SWING"
        selected = swing
        reasons = swing_reasons
    else:
        mode = "NONE"
        selected = max(scalp, swing)
        reasons = scalp_reasons if scalp >= swing else swing_reasons
    frame_bias = {
        timeframe: str(ctx.get("bias", "UNKNOWN"))
        for timeframe, ctx in mtf_frames.items()
    }
    frame_strength = {
        timeframe: int(ctx.get("strength", 0) or 0)
        for timeframe, ctx in mtf_frames.items()
    }

    return {
        "symbol": symbol,
        "score": selected,
        "signal": "BUY" if mode != "NONE" else "HOLD",
        "trade_mode": mode,
        "swing_score": swing,
        "scalp_score": scalp,
        "swing_signal": swing_signal,
        "scalp_signal": scalp_signal,
        "scalp_gate": gate,
        "scalp_gate_reasons": gate_reasons,
        "scalp_confirmed_reversal": confirmed_reversal,
        "scalp_high_confidence_recovery": high_confidence_recovery,
        "scalp_recovery_confirmation": recovery_confirmation,
        "scalp_recovery_trigger_count": recovery_trigger_count,
        "scalp_recovery_trigger_reasons": recovery_trigger_reasons,
        "scalp_context_only": bool(scalp >= SCALP_SCORE_THRESHOLD and not recovery_confirmation and not confirmed_reversal),
        "scalp_min_volume_ratio": SCALP_MIN_VOLUME_RATIO,
        "scalp_max_rsi": SCALP_MAX_RSI,
        "scalp_rsi_rise_min": SCALP_RSI_RISE_MIN,
        "scalp_recovery_trigger_min": SCALP_RECOVERY_TRIGGER_MIN,
        "scalp_recovery_points": SCALP_RECOVERY_POINTS,
        "scalp_score_raw": scalp_raw,
        "scalp_reversion_family_points": reversion_points,
        "scalp_structural_confirmation": structural["confirmed"],
        "scalp_structural_higher_low": structural["higher_low"],
        "scalp_structural_two_candle_reclaim": structural["two_candle_reclaim"],
        "scalp_structural_seller_failure": structural["seller_failure"],
        "scalp_structural_five_m_bias": structural["five_m_bias"],
        "scalp_structural_fifteen_m_bias": structural["fifteen_m_bias"],
        "scalp_structural_higher_low_timeframes": structural["higher_low_timeframes"],
        "mtf_context_available": bool(mtf.get("available")),
        "mtf_bias": str(mtf.get("bias", "UNKNOWN")),
        "mtf_net": int(mtf.get("net", 0) or 0),
        "mtf_weighted_bull": int(mtf.get("weighted_bull", 0) or 0),
        "mtf_weighted_bear": int(mtf.get("weighted_bear", 0) or 0),
        "mtf_higher_timeframes_bearish": bool(mtf.get("higher_timeframes_bearish")),
        "mtf_higher_timeframes_bullish": bool(mtf.get("higher_timeframes_bullish")),
        "mtf_countertrend_warning": mtf_bearish,
        "mtf_strong_bearish_stack": mtf_strong_bearish_stack,
        "mtf_countertrend_veto": mtf_countertrend_veto,
        "mtf_aligned_bullish": mtf_bullish,
        "mtf_timeframe_bias": frame_bias,
        "mtf_timeframe_strength": frame_strength,
        "mtf_patterns": {
            timeframe: list(ctx.get("patterns", []))
            for timeframe, ctx in mtf_frames.items()
        },
        "seller_failure_confirmed": seller_failure_confirmed,
        "reasons": reasons,
        "swing_reasons": swing_reasons,
        "scalp_reasons": scalp_reasons,
        "price": price,
        "ema100": ema100,
        "rsi": r15,
        "rsi5m": r5,
        "atr": atr,
        "atr5m": atr5,
        "lower_band": lo15,
        "middle_band": mid15,
        "upper_band": up15,
        "lower_band_5m": lo5,
        "middle_band_5m": mid5,
        "upper_band_5m": up5,
        "volume_ratio": v15,
        "volume_ratio_5m": v5,
        "pattern": name,
        "pattern_confirmed": confirmed,
    }
