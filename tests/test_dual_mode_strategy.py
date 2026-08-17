from __future__ import annotations

import shadow_main
import shadow_main_legacy
from dual_mode_strategy import BUY_SCORE_THRESHOLD, SCALP_SCORE_THRESHOLD, SWING_SCORE_THRESHOLD, score_symbol


def candle(open_price: float, high: float, low: float, close: float, volume: float = 100.0) -> dict:
    return {"open": open_price, "high": high, "low": low, "close": close, "volume": volume}


def rising_series(count: int, start: float = 100.0) -> list[dict]:
    return [candle(start + i * 0.05, start + i * 0.08, start + i * 0.02, start + i * 0.06) for i in range(count)]


def test_dual_mode_thresholds_are_separated():
    assert SCALP_SCORE_THRESHOLD < SWING_SCORE_THRESHOLD
    assert BUY_SCORE_THRESHOLD == SWING_SCORE_THRESHOLD
    assert SCALP_SCORE_THRESHOLD == 65
    assert shadow_main.score_symbol is score_symbol


def test_original_shadow_runtime_is_preserved_and_reused():
    assert hasattr(shadow_main_legacy, "process_market_cycle")
    assert hasattr(shadow_main_legacy, "runtime")
    assert shadow_main.runtime is shadow_main_legacy.runtime
    assert shadow_main.app is shadow_main_legacy.app


def test_score_exposes_independent_scalp_and_swing_lanes():
    candles_15m = rising_series(130, 100.0)
    candles_5m = rising_series(30, 100.0)
    result = score_symbol("TESTUSDT", {"lastPrice": "106.5"}, candles_15m, candles_5m)
    assert "scalp_score" in result
    assert "swing_score" in result
    assert result["scalp_signal"] in {"BUY", "HOLD"}
    assert result["swing_signal"] in {"BUY", "HOLD"}


def test_scalp_gate_rejects_without_confirmed_reversal():
    candles_15m = rising_series(130, 100.0)
    candles_5m = rising_series(30, 100.0)
    candles_5m[-2] = candle(99.0, 101.0, 98.5, 100.2, 160.0)
    candles_5m[-1] = candle(100.2, 100.4, 99.8, 100.0, 100.0)
    result = score_symbol("TESTUSDT", {"lastPrice": "100.0"}, candles_15m, candles_5m)
    assert result["scalp_signal"] == "HOLD"
    assert result["scalp_gate"] is False


def test_existing_swing_lane_can_still_reach_buy():
    candles_15m = rising_series(130, 100.0)
    for i in range(20):
        base = 106.0 - i * 0.05
        candles_15m[-20 + i] = candle(base + 0.5, base + 0.6, base - 0.2, base)
    candles_15m[-2] = candle(102.0, 102.5, 100.5, 104.5, 150.0)
    candles_15m[-1] = candle(105.0, 105.3, 101.0, 101.5, 100.0)
    candles_5m = rising_series(21, 100.0)
    candles_5m[-2] = candle(99.0, 103.0, 98.8, 102.5, 120.0)
    candles_5m[-1] = candle(102.5, 102.7, 101.8, 102.4, 100.0)
    result = score_symbol("TESTUSDT", {"lastPrice": "104.5"}, candles_15m, candles_5m)
    assert result["swing_score"] >= SWING_SCORE_THRESHOLD
    assert result["swing_signal"] == "BUY"
    assert result["pattern_confirmed"] is True


def test_strategy_universe_remains_16_spot_pairs():
    assert len(shadow_main.TRADING_SYMBOLS) == 16

# CI trigger checkpoint: safe adapter preserves original runtime composition.
