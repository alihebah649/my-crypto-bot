from __future__ import annotations

from types import SimpleNamespace

import dual_mode_strategy


def _candle(o: float, h: float, l: float, c: float, volume: float = 100.0) -> dict:
    return {"open": o, "high": h, "low": l, "close": c, "volume": volume}


def test_both_lane_signals_can_qualify_independently(monkeypatch):
    monkeypatch.setattr(dual_mode_strategy, "calculate_rsi", lambda prices, period=14: 40.0)
    monkeypatch.setattr(dual_mode_strategy, "calculate_bollinger", lambda candles, period=20, deviations=2.0: (100.0, 110.0, 120.0))
    monkeypatch.setattr(dual_mode_strategy, "_volume_ratio", lambda candles, window=20: 1.20)
    monkeypatch.setattr(dual_mode_strategy, "bullish_pattern", lambda candles: (True, "BULLISH_BREAKOUT", True))

    candles_15m = [_candle(100 + i * 0.02, 101 + i * 0.02, 99 + i * 0.02, 100.5 + i * 0.02) for i in range(130)]
    candles_5m = [_candle(100 + i * 0.01, 101 + i * 0.01, 99 + i * 0.01, 100.5 + i * 0.01) for i in range(30)]

    result = dual_mode_strategy.score_symbol("TESTUSDT", {"lastPrice": "100.0"}, candles_15m, candles_5m)

    assert result["scalp_signal"] == "BUY"
    assert result["swing_signal"] == "BUY"
    # The strategy's legacy scalar mode remains SCALP for backward compatibility;
    # orchestration consumes both independent lane signals.
    assert result["trade_mode"] == "SCALP"


def test_runtime_has_lane_aware_position_guard():
    import shadow_main

    shadow_main._legacy.latest_scores["TESTUSDT"] = {
        "scalp_signal": "BUY",
        "swing_signal": "BUY",
    }
    try:
        assert shadow_main._active_trade_modes("TESTUSDT") == set()
        assert shadow_main._lane_aware_has_position("TESTUSDT") is False
    finally:
        shadow_main._legacy.latest_scores.pop("TESTUSDT", None)


def test_existing_scalp_does_not_block_swing_lane(monkeypatch):
    import shadow_main

    position = SimpleNamespace(
        symbol="TESTUSDT",
        status=SimpleNamespace(name="OPEN"),
        entry_metadata={"trade_mode": "SCALP"},
    )
    monkeypatch.setattr(shadow_main.runtime.repository, "get_by_symbol", lambda symbol: [position])
    shadow_main._legacy.latest_scores["TESTUSDT"] = {
        "scalp_signal": "HOLD",
        "swing_signal": "BUY",
    }
    try:
        assert shadow_main._active_trade_modes("TESTUSDT") == {"SCALP"}
        assert shadow_main._lane_aware_has_position("TESTUSDT") is False
    finally:
        shadow_main._legacy.latest_scores.pop("TESTUSDT", None)


def test_same_lane_is_still_blocked(monkeypatch):
    import shadow_main

    position = SimpleNamespace(
        symbol="TESTUSDT",
        status=SimpleNamespace(name="OPEN"),
        entry_metadata={"trade_mode": "SCALP"},
    )
    monkeypatch.setattr(shadow_main.runtime.repository, "get_by_symbol", lambda symbol: [position])
    shadow_main._legacy.latest_scores["TESTUSDT"] = {
        "scalp_signal": "BUY",
        "swing_signal": "HOLD",
    }
    try:
        assert shadow_main._lane_aware_has_position("TESTUSDT") is True
    finally:
        shadow_main._legacy.latest_scores.pop("TESTUSDT", None)


def test_runtime_opens_both_qualified_lanes(monkeypatch):
    import shadow_main

    shadow_main._legacy.latest_scores["TESTUSDT"] = {
        "scalp_signal": "BUY",
        "swing_signal": "BUY",
        "trade_mode": "SCALP",
    }
    opened_modes = []

    def fake_open(symbol, entry_price, stop_loss, trade_mode):
        opened_modes.append(trade_mode)
        return SimpleNamespace(
            position_id=f"{trade_mode.lower()}-1",
            entry_metadata={"trade_mode": trade_mode},
            metadata={},
        )

    monkeypatch.setattr(shadow_main, "_original_runtime_open_position", fake_open)
    monkeypatch.setattr(shadow_main.runtime.repository, "update", lambda position: None)
    shadow_main.runtime.last_entry_diagnostics.pop("TESTUSDT", None)

    try:
        position = shadow_main._open_position_with_selected_mode("TESTUSDT", 100.0, 98.0)
        assert position is not None
        assert opened_modes == ["SCALP", "SWING"]
        trace = shadow_main.runtime.last_entry_diagnostics["TESTUSDT"]
        assert trace["trade_modes_requested"] == ["SCALP", "SWING"]
        assert trace["trade_modes_opened"] == ["SCALP", "SWING"]
        assert trace["dual_lane_entry"] is True
    finally:
        shadow_main._legacy.latest_scores.pop("TESTUSDT", None)
        shadow_main.runtime.last_entry_diagnostics.pop("TESTUSDT", None)


def test_existing_lane_is_skipped_when_both_signals_qualify(monkeypatch):
    import shadow_main

    existing_scalp = SimpleNamespace(
        symbol="TESTUSDT",
        status=SimpleNamespace(name="OPEN"),
        entry_metadata={"trade_mode": "SCALP"},
    )
    monkeypatch.setattr(shadow_main.runtime.repository, "get_by_symbol", lambda symbol: [existing_scalp])
    monkeypatch.setattr(shadow_main.runtime.repository, "update", lambda position: None)

    shadow_main._legacy.latest_scores["TESTUSDT"] = {
        "scalp_signal": "BUY",
        "swing_signal": "BUY",
    }
    opened_modes = []

    def fake_open(symbol, entry_price, stop_loss, trade_mode):
        opened_modes.append(trade_mode)
        return SimpleNamespace(
            position_id=f"{trade_mode.lower()}-2",
            entry_metadata={"trade_mode": trade_mode},
            metadata={},
        )

    monkeypatch.setattr(shadow_main, "_original_runtime_open_position", fake_open)
    shadow_main.runtime.last_entry_diagnostics.pop("TESTUSDT", None)

    try:
        shadow_main._open_position_with_selected_mode("TESTUSDT", 100.0, 98.0)
        assert opened_modes == ["SWING"]
        trace = shadow_main.runtime.last_entry_diagnostics["TESTUSDT"]
        assert trace["trade_modes_skipped_existing"] == ["SCALP"]
        assert trace["trade_modes_opened"] == ["SWING"]
        assert trace["dual_lane_entry"] is False
    finally:
        shadow_main._legacy.latest_scores.pop("TESTUSDT", None)
        shadow_main.runtime.last_entry_diagnostics.pop("TESTUSDT", None)
