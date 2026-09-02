from __future__ import annotations

from types import SimpleNamespace

import shadow_main


def test_shadow_entry_handoff_preserves_explicit_scalp_mode(monkeypatch):
    symbol = "FETUSDT"
    captured = {}
    position = SimpleNamespace(entry_metadata={}, metadata={})

    def fake_runtime_open_position(symbol, entry_price, stop_loss, trade_mode="SWING"):
        captured["trade_mode"] = trade_mode
        return position

    monkeypatch.setattr(shadow_main, "_original_runtime_open_position", fake_runtime_open_position)
    monkeypatch.setitem(shadow_main._legacy.latest_scores, symbol, {"signal": "BUY", "score": 68, "trade_mode": "SCALP"})

    result = shadow_main._open_position_with_selected_mode(symbol, 100.0, 96.0)

    assert result is position
    assert captured["trade_mode"] == "SCALP"
    assert shadow_main._current_trade_mode["value"] == "SCALP"
    assert position.entry_metadata["trade_mode"] == "SCALP"
    assert position.metadata["trade_mode"] == "SCALP"
    assert shadow_main.runtime.last_entry_diagnostics[symbol]["trade_mode"] == "SCALP"


def test_invalid_strategy_mode_falls_back_to_swing(monkeypatch):
    captured = {}
    position = SimpleNamespace(entry_metadata={}, metadata={})

    def fake_runtime_open_position(symbol, entry_price, stop_loss, trade_mode="SWING"):
        captured["trade_mode"] = trade_mode
        return position

    monkeypatch.setattr(shadow_main, "_original_runtime_open_position", fake_runtime_open_position)
    monkeypatch.setitem(shadow_main._legacy.latest_scores, "FETUSDT", {"signal": "BUY", "score": 68, "trade_mode": "INVALID"})

    shadow_main._open_position_with_selected_mode("FETUSDT", 100.0, 96.0)

    assert captured["trade_mode"] == "SWING"
    assert shadow_main._current_trade_mode["value"] == "SWING"
    assert position.entry_metadata["trade_mode"] == "SWING"
    assert position.metadata["trade_mode"] == "SWING"
