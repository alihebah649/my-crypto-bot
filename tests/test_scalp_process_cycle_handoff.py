from __future__ import annotations

import shadow_main
from trade_manager.models import Position, PositionSide, PositionStatus


def _position() -> Position:
    return Position(
        position_id="test-scalp-process-cycle",
        symbol="FETUSDT",
        side=PositionSide.LONG,
        status=PositionStatus.OPEN,
        quantity=0.5,
        entry_price=100.0,
        current_price=100.0,
        stop_loss=96.0,
        take_profit=None,
    )


def test_generated_scalp_signal_reaches_selected_mode_runtime(monkeypatch):
    symbol = "FETUSDT"
    score = {
        "symbol": symbol,
        "price": 100.0,
        "atr": 2.0,
        "score": 68,
        "scalp_score": 68,
        "scalp_gate": True,
        "scalp_signal": "BUY",
        "swing_score": 0,
        "swing_signal": "HOLD",
        "trade_mode": "SCALP",
        "signal": "BUY",
    }
    position = _position()
    captured = {}

    monkeypatch.setitem(shadow_main._legacy.latest_scores, symbol, score)
    monkeypatch.setattr(shadow_main, "_active_trade_modes", lambda requested_symbol: set())

    def fake_open_one_position(requested_symbol, entry_price, stop_loss, mode):
        captured["symbol"] = requested_symbol
        captured["entry_price"] = entry_price
        captured["stop_loss"] = stop_loss
        captured["mode"] = mode
        # Match the contract of the real helper: opened positions carry the
        # selected lane in both metadata stores used by the orchestrator trace.
        position.entry_metadata["trade_mode"] = mode
        position.metadata["trade_mode"] = mode
        return position

    monkeypatch.setattr(shadow_main, "_open_one_position", fake_open_one_position)

    result = shadow_main._open_position_with_selected_mode(symbol, 100.0, 96.0)

    assert result is position
    assert captured == {
        "symbol": symbol,
        "entry_price": 100.0,
        "stop_loss": 96.0,
        "mode": "SCALP",
    }

    trace = shadow_main.runtime.last_entry_diagnostics[symbol]
    assert trace["trade_modes_requested"] == ["SCALP"]
    assert trace["trade_modes_skipped_existing"] == []
    assert trace["trade_modes_opened"] == ["SCALP"]
    assert trace["dual_lane_entry"] is False
    assert trace["trade_mode"] == "SCALP"
    assert trace["positions_opened"] == [position.position_id]
