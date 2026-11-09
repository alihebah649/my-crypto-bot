from core.paper_signal_cycle_summary import build_paper_signal_cycle_summary


def test_cycle_summary_separates_score_threshold_from_actual_buy_signal():
    scores = {
        "BTCUSDT": {
            "score": 73,
            "trade_mode": "NONE",
            "scalp_score": 73,
            "scalp_signal": "HOLD",
            "scalp_gate": False,
            "scalp_gate_reasons": [
                "SCALP_CONTEXT_ONLY_NO_RECOVERY_TRIGGER",
                "SCALP_STRUCTURE_NOT_CONFIRMED",
            ],
            "swing_score": 58,
            "swing_signal": "HOLD",
        },
        "ETHUSDT": {
            "score": 69,
            "trade_mode": "SCALP",
            "scalp_score": 69,
            "scalp_signal": "BUY",
            "scalp_gate": True,
            "scalp_gate_reasons": ["CONFIRMED_5M_REVERSAL"],
            "swing_score": 62,
            "swing_signal": "HOLD",
        },
        "SOLUSDT": {
            "score": 82,
            "trade_mode": "NONE",
            "scalp_score": 61,
            "scalp_signal": "HOLD",
            "scalp_gate": False,
            "scalp_gate_reasons": ["NO_15M_MACRO_SUPPORT"],
            "swing_score": 82,
            "swing_signal": "HOLD",
        },
    }

    result = build_paper_signal_cycle_summary(scores, venue_mode="MIXED")

    assert result["mode"] == "PAPER_ONLY"
    assert result["symbol_count"] == 3
    assert result["scalp_scores_at_or_above_threshold"] == 2
    assert result["scalp_signals_buy"] == 1
    assert result["scalp_threshold_met_but_not_buy"] == 1
    assert result["scalp_gate_blocked_at_threshold"] == 1
    assert result["scalp_gate_block_reasons"] == {
        "SCALP_CONTEXT_ONLY_NO_RECOVERY_TRIGGER": 1,
        "SCALP_STRUCTURE_NOT_CONFIRMED": 1,
    }
    assert result["swing_scores_at_or_above_threshold"] == 1
    assert result["swing_signals_buy"] == 0
    assert result["swing_threshold_met_but_not_buy"] == 1
    assert result["buy_symbols"] == ["ETHUSDT"]
    assert result["threshold_candidates"][0]["symbol"] in {"BTCUSDT", "ETHUSDT", "SOLUSDT"}
    assert result["interpretation"]["trading_logic_changed"] is False


def test_cycle_summary_handles_empty_score_universe():
    result = build_paper_signal_cycle_summary({}, venue_mode="MIXED")

    assert result["symbol_count"] == 0
    assert result["scalp_scores_at_or_above_threshold"] == 0
    assert result["swing_scores_at_or_above_threshold"] == 0
    assert result["buy_symbol_count"] == 0
    assert result["top_scores"] == []
