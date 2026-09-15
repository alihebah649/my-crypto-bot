from __future__ import annotations


def test_scalp_diagnostic_payload_contains_gate_components():
    result = {
        "symbol": "TESTUSDT",
        "score": 69,
        "scalp_score": 69,
        "swing_score": 20,
        "scalp_signal": "HOLD",
        "trade_mode": "NONE",
        "scalp_gate": False,
        "scalp_gate_reasons": ["5M_VOLUME_TOO_LOW"],
        "scalp_confirmed_reversal": False,
        "scalp_recovery_confirmation": True,
        "scalp_recovery_trigger_count": 2,
        "scalp_recovery_trigger_reasons": ["5M_RSI_RISING", "5M_PRICE_RECOVERY"],
        "scalp_context_only": False,
        "volume_ratio_5m": 0.71,
        "scalp_min_volume_ratio": 0.75,
        "rsi5m": 41.2,
        "scalp_max_rsi": 55.0,
        "pattern": "NEUTRAL",
        "pattern_confirmed": False,
        "mtf_countertrend_warning": False,
        "mtf_countertrend_veto": False,
        "mtf_aligned_bullish": False,
        "entry_freshness_state": "FRESH",
        "manager_cache_age_seconds": 5.0,
        "cache_source": "REFRESHED",
    }

    required = {
        "symbol", "score", "scalp_score", "scalp_gate", "scalp_gate_reasons",
        "scalp_confirmed_reversal", "scalp_recovery_confirmation",
        "scalp_recovery_trigger_count", "volume_ratio_5m",
        "scalp_min_volume_ratio", "rsi5m", "scalp_max_rsi", "pattern",
        "pattern_confirmed", "mtf_countertrend_veto", "entry_freshness_state",
        "manager_cache_age_seconds", "cache_source",
    }
    assert required <= result.keys()
    assert result["scalp_score"] >= 65
    assert result["scalp_gate"] is False
    assert "5M_VOLUME_TOO_LOW" in result["scalp_gate_reasons"]
