from __future__ import annotations

from shadow_main import BUY_SCORE_THRESHOLD, TRADING_SYMBOLS, score_symbol


def candle(open_price: float, high: float, low: float, close: float, volume: float = 100.0) -> dict:
    return {
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }


def rising_series(count: int, start: float = 100.0) -> list[dict]:
    return [
        candle(start + i * 0.05, start + i * 0.08, start + i * 0.02, start + i * 0.06)
        for i in range(count)
    ]


def test_strategy_universe_contains_the_established_16_spot_pairs():
    assert len(TRADING_SYMBOLS) == 16
    assert {
        "BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "ADAUSDT", "DOTUSDT",
        "NEARUSDT", "ARBUSDT", "OPUSDT", "RENDERUSDT", "BNBUSDT", "AVAXUSDT",
        "ALGOUSDT", "ATOMUSDT", "FETUSDT", "LTCUSDT",
    } == set(TRADING_SYMBOLS)


def test_score_can_reach_buy_without_requiring_btc_specific_conditions():
    # Construct a generic symbol with four independent score components:
    # EMA support, oversold RSI, lower-half Bollinger context, volume
    # confirmation, plus a confirmed 5m breakout on a CLOSED candle.
    # The last candle is deliberately left as the forming candle because
    # shadow_main.py intentionally excludes forming candles from the signal.
    candles_15m = rising_series(130, 100.0)
    for i in range(20):
        base = 106.0 - i * 0.05
        candles_15m[-20 + i] = candle(base + 0.5, base + 0.6, base - 0.2, base)
    candles_15m[-2] = candle(102.0, 102.5, 100.5, 104.5, 150.0)
    candles_15m[-1] = candle(105.0, 105.3, 101.0, 101.5, 100.0)

    candles_5m = rising_series(20, 100.0)
    candles_5m[-2] = candle(99.0, 103.0, 98.8, 102.5, 120.0)
    candles_5m[-1] = candle(102.5, 102.7, 101.8, 102.4, 100.0)

    ticker = {"lastPrice": "104.5"}
    result = score_symbol("TESTUSDT", ticker, candles_15m, candles_5m)

    assert result["score"] <= 100
    assert result["score"] >= BUY_SCORE_THRESHOLD
    assert result["signal"] == "BUY"
    assert result["pattern_confirmed"] is True


def test_bullish_continuation_can_trigger_swing_without_macro_support_dip():
    # Healthy uptrend: price is above EMA100 and in the upper half of the
    # 15m Bollinger channel. Swing must not require a lower-band pullback.
    candles_15m = [candle(100.0, 100.1, 99.9, 100.0) for _ in range(100)]
    for i in range(20):
        close = 100.0 + i * 0.01
        candles_15m[-20 + i] = candle(close - 0.005, close + 0.02, close - 0.02, close, 100.0)
    candles_15m[-2] = candle(100.10, 100.13, 100.08, 100.12, 150.0)
    candles_15m[-1] = candle(100.12, 100.15, 100.10, 100.13, 100.0)

    candles_5m = [candle(100.0, 100.1, 99.9, 100.0) for _ in range(20)]
    candles_5m[-3] = candle(99.8, 100.0, 99.7, 99.9, 100.0)
    candles_5m[-2] = candle(99.9, 100.5, 99.85, 100.4, 150.0)
    candles_5m[-1] = candle(100.4, 100.45, 100.2, 100.42, 100.0)

    result = score_symbol("SWINGTESTUSDT", {"lastPrice": "100.3"}, candles_15m, candles_5m)

    assert result["swing_score"] >= 80
    assert result["swing_signal"] == "BUY"
    assert result["trade_mode"] == "SWING"
    assert result["scalp_signal"] == "HOLD"
    assert "BULLISH_TREND_CONTINUATION" in result["swing_reasons"]


def test_score_stays_hold_when_only_ema_condition_is_present():
    candles_15m = rising_series(130, 100.0)
    candles_5m = rising_series(20, 100.0)
    result = score_symbol(
        "TESTUSDT",
        {"lastPrice": "106.5"},
        candles_15m,
        candles_5m,
    )
    assert result["score"] < BUY_SCORE_THRESHOLD
    assert result["signal"] == "HOLD"
