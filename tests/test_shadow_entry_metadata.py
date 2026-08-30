from trade_manager.models import Position, PositionSide, PositionStatus


def test_shadow_entry_captures_complete_strategy_context(monkeypatch):
    import shadow_main

    decision = {
        "symbol": "BTCUSDT",
        "score": 72,
        "trade_mode": "SCALP",
        "scalp_score": 72,
        "scalp_gate": True,
        "reasons": ["15M_BOLLINGER_LOWER_HALF", "5M_RSI_RECOVERY_ZONE"],
        "mtf_bias": "BULLISH",
        "mtf_aligned_bullish": True,
        "mtf_timeframe_bias": {"5m": "BULLISH", "15m": "BULLISH", "1h": "BULLISH", "4h": "NEUTRAL"},
        "mtf_timeframe_strength": {"5m": 2, "15m": 2, "1h": 1, "4h": 0},
        "mtf_patterns": {"5m": ["BULLISH_OUTSIDE"], "15m": []},
        "scalp_recovery_confirmation": True,
        "scalp_recovery_trigger_count": 3,
        "scalp_recovery_trigger_reasons": ["5M_RSI_RISING", "5M_PRICE_RECOVERY", "5M_BULLISH_BODY"],
        "pattern": "BULLISH_OUTSIDE",
        "pattern_confirmed": True,
    }
    position = Position(
        position_id="pos-context-1", symbol="BTCUSDT", side=PositionSide.LONG,
        status=PositionStatus.OPEN, quantity=0.1, entry_price=100.0,
        current_price=100.0, stop_loss=98.0, take_profit=None,
    )

    monkeypatch.setattr(shadow_main._legacy, "latest_scores", {"BTCUSDT": decision})
    monkeypatch.setattr(shadow_main, "_original_runtime_open_position", lambda *args, **kwargs: position)
    monkeypatch.setattr(shadow_main.runtime.repository, "update", lambda p: None)

    result = shadow_main._open_position_with_selected_mode("BTCUSDT", 100.0, 98.0)

    assert result is position
    assert result.entry_metadata["trade_mode"] == "SCALP"
    assert result.entry_metadata["strategy_context"] == decision
    assert result.metadata["strategy_context"]["score"] == 72
    assert result.metadata["strategy_context"]["mtf_timeframe_bias"]["1h"] == "BULLISH"
    assert result.metadata["strategy_context"]["scalp_recovery_trigger_count"] == 3
