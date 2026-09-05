from __future__ import annotations

import shadow_main
import shadow_main_legacy
import dual_mode_strategy
from dual_mode_strategy import BUY_SCORE_THRESHOLD, SCALP_SCORE_THRESHOLD, SWING_SCORE_THRESHOLD, score_symbol


def candle(open_price: float, high: float, low: float, close: float, volume: float = 100.0) -> dict:
    return {"open": open_price, "high": high, "low": low, "close": close, "volume": volume}


def rising_series(count: int, start: float = 100.0) -> list[dict]:
    return [candle(start + i * 0.05, start + i * 0.08, start + i * 0.02, start + i * 0.06) for i in range(count)]


def test_dual_mode_thresholds_are_separated():
    assert SCALP_SCORE_THRESHOLD < SWING_SCORE_THRESHOLD
    assert BUY_SCORE_THRESHOLD == SWING_SCORE_THRESHOLD
    assert SCALP_SCORE_THRESHOLD == 65
    assert dual_mode_strategy.SCALP_MAX_RSI == 55.0
    assert dual_mode_strategy.SCALP_RSI_RISE_MIN == 1.5
    assert dual_mode_strategy.SCALP_RECOVERY_TRIGGER_MIN == 2
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


def test_scalp_context_score_cannot_trigger_entry_without_recovery(monkeypatch):
    monkeypatch.setattr(dual_mode_strategy, "calculate_rsi", lambda prices, period=14: 35.0)
    monkeypatch.setattr(dual_mode_strategy, "calculate_bollinger", lambda candles, period=20, deviations=2.0: (100.0, 110.0, 120.0))
    monkeypatch.setattr(dual_mode_strategy, "_volume_ratio", lambda candles, window=20: 1.20)
    monkeypatch.setattr(dual_mode_strategy, "bullish_pattern", lambda candles: (False, "NEUTRAL", False))
    candles_15m = rising_series(130, 100.0)
    candles_5m = rising_series(30, 100.0)
    candles_5m[-3] = candle(100.0, 100.2, 98.5, 99.0, 120.0)
    candles_5m[-2] = candle(99.0, 99.2, 97.8, 98.0, 120.0)
    result = score_symbol("TESTUSDT", {"lastPrice": "98.0"}, candles_15m, candles_5m)
    assert result["scalp_score"] >= SCALP_SCORE_THRESHOLD
    assert result["scalp_context_only"] is True
    assert result["scalp_recovery_confirmation"] is False
    assert result["scalp_gate"] is False
    assert result["scalp_signal"] == "HOLD"
    assert "SCALP_CONTEXT_ONLY_NO_RECOVERY_TRIGGER" in result["scalp_gate_reasons"]


def test_scalp_recovery_trigger_can_authorize_65_plus_without_pattern(monkeypatch):
    rsi_values = iter([40.0, 35.0, 33.0])
    monkeypatch.setattr(dual_mode_strategy, "calculate_rsi", lambda prices, period=14: next(rsi_values))
    monkeypatch.setattr(dual_mode_strategy, "calculate_bollinger", lambda candles, period=20, deviations=2.0: (100.0, 110.0, 120.0))
    monkeypatch.setattr(dual_mode_strategy, "_volume_ratio", lambda candles, window=20: 1.20)
    monkeypatch.setattr(dual_mode_strategy, "bullish_pattern", lambda candles: (False, "NEUTRAL", False))
    candles_15m = rising_series(130, 100.0)
    candles_5m = rising_series(30, 100.0)
    candles_5m[-3] = candle(99.0, 99.5, 97.8, 98.0, 120.0)
    candles_5m[-2] = candle(98.0, 99.0, 97.9, 98.6, 120.0)
    result = score_symbol("TESTUSDT", {"lastPrice": "98.6"}, candles_15m, candles_5m)
    assert result["scalp_score"] >= SCALP_SCORE_THRESHOLD
    assert result["scalp_recovery_trigger_count"] >= dual_mode_strategy.SCALP_RECOVERY_TRIGGER_MIN
    assert result["scalp_recovery_confirmation"] is True
    assert result["scalp_gate"] is True
    assert result["scalp_signal"] == "BUY"
    assert result["trade_mode"] == "SCALP"


def test_scalp_gate_rejects_without_confirmed_reversal():
    candles_15m = rising_series(130, 100.0)
    candles_5m = rising_series(30, 100.0)
    candles_5m[-3] = candle(99.0, 101.0, 98.5, 100.2, 160.0)
    candles_5m[-2] = candle(100.2, 100.4, 99.8, 100.0, 100.0)
    result = score_symbol("TESTUSDT", {"lastPrice": "100.0"}, candles_15m, candles_5m)
    assert result["scalp_signal"] == "HOLD"
    assert result["scalp_gate"] is False


def test_scalp_gate_accepts_confirmed_reversal_at_rsi_50(monkeypatch):
    monkeypatch.setattr(dual_mode_strategy, "calculate_rsi", lambda prices, period=14: 50.0)
    monkeypatch.setattr(dual_mode_strategy, "calculate_bollinger", lambda candles, period=20, deviations=2.0: (100.0, 110.0, 120.0))
    monkeypatch.setattr(dual_mode_strategy, "_volume_ratio", lambda candles, window=20: 1.20)
    monkeypatch.setattr(dual_mode_strategy, "bullish_pattern", lambda candles: (True, "BULLISH_BREAKOUT", True))
    candles_15m = rising_series(130, 100.0)
    candles_5m = rising_series(30, 100.0)
    result = score_symbol("TESTUSDT", {"lastPrice": "100.0"}, candles_15m, candles_5m)
    assert result["scalp_score"] >= SCALP_SCORE_THRESHOLD
    assert result["scalp_max_rsi"] == 55.0
    assert result["scalp_gate"] is True
    assert result["scalp_signal"] == "BUY"
    assert result["trade_mode"] == "SCALP"


def test_scalp_gate_rejects_confirmed_reversal_above_rsi_55(monkeypatch):
    monkeypatch.setattr(dual_mode_strategy, "calculate_rsi", lambda prices, period=14: 56.0)
    monkeypatch.setattr(dual_mode_strategy, "calculate_bollinger", lambda candles, period=20, deviations=2.0: (100.0, 110.0, 120.0))
    monkeypatch.setattr(dual_mode_strategy, "_volume_ratio", lambda candles, window=20: 1.20)
    monkeypatch.setattr(dual_mode_strategy, "bullish_pattern", lambda candles: (True, "BULLISH_BREAKOUT", True))
    candles_15m = rising_series(130, 100.0)
    candles_5m = rising_series(30, 100.0)
    result = score_symbol("TESTUSDT", {"lastPrice": "100.0"}, candles_15m, candles_5m)
    assert result["scalp_score"] >= SCALP_SCORE_THRESHOLD
    assert result["scalp_gate"] is False
    assert result["scalp_signal"] == "HOLD"


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


def test_strategy_universe_remains_22_spot_pairs():
    assert len(shadow_main.TRADING_SYMBOLS) == 22

# CI trigger checkpoint: safe adapter preserves original runtime composition.
# The legacy runtime remains the execution authority.
