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
            "swing_signal": "BUY",
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
    assert result["swing_signals_buy"] == 1
    assert result["swing_threshold_met_but_not_buy"] == 0
    assert result["buy_symbols"] == ["ETHUSDT", "SOLUSDT"]
    assert result["threshold_candidates"][0]["symbol"] == "SOLUSDT"
    assert result["interpretation"]["trading_logic_changed"] is False


def test_cycle_summary_handles_empty_score_universe():
    result = build_paper_signal_cycle_summary({}, venue_mode="MIXED")

    assert result["symbol_count"] == 0
    assert result["scalp_scores_at_or_above_threshold"] == 0
    assert result["swing_scores_at_or_above_threshold"] == 0
    assert result["buy_symbol_count"] == 0
    assert result["top_scores"] == []


def test_cycle_summary_compares_prior_scalp_formula_without_approving_current_signal():
    result = build_paper_signal_cycle_summary(
        {
            "BTCUSDT": {
                "score": 61,
                "trade_mode": "NONE",
                "scalp_score": 61,
                "scalp_signal": "HOLD",
                "scalp_gate": False,
                "scalp_gate_reasons": ["SCALP_STRUCTURE_NOT_CONFIRMED"],
                "scalp_score_raw": 95,
                "scalp_pre_calibration_score": 100,
                "scalp_pre_calibration_gate": True,
                "scalp_pre_calibration_signal": "BUY",
                "scalp_reversion_family_points": 22,
                "rsi5m": 20,
                "volume_ratio_5m": 1.2,
                "pattern": "BULLISH_REVERSAL",
                "pattern_confirmed": True,
                "scalp_recovery_confirmation": True,
                "scalp_structural_confirmation": False,
                "mtf_bias": "NEUTRAL",
                "mtf_net": 0,
                "swing_score": 53,
                "swing_signal": "HOLD",
            },
            "ETHUSDT": {
                "score": 42,
                "trade_mode": "NONE",
                "scalp_score": 30,
                "scalp_signal": "HOLD",
                "scalp_gate": False,
                "scalp_gate_reasons": ["5M_VOLUME_TOO_LOW"],
                "scalp_pre_calibration_score": 42,
                "scalp_pre_calibration_gate": False,
                "scalp_pre_calibration_signal": "HOLD",
                "swing_score": 42,
                "swing_signal": "HOLD",
            },
        },
        venue_mode="MIXED",
    )

    assert result["scalp_scores_at_or_above_threshold"] == 0
    assert result["scalp_signals_buy"] == 0
    assert result["scalp_pre_calibration_scores_at_or_above_threshold"] == 1
    assert result["scalp_pre_calibration_signals_buy"] == 1
    assert result["scalp_pre_calibration_only_signals"] == 1
    assert result["scalp_gate_reason_counts_all_symbols"] == {
        "5M_VOLUME_TOO_LOW": 1,
        "SCALP_STRUCTURE_NOT_CONFIRMED": 1,
    }
    assert result["scalp_pre_calibration_candidates"][0]["symbol"] == "BTCUSDT"
    assert result["interpretation"]["trading_logic_changed"] is False
