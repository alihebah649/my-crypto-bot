from core.paper_entry_outcome_forensics import build_linked_entry_outcome_analysis


def test_classifier_shadows_link_to_closed_position_and_keep_pnl_fee_net():
    capture = {
        "capture_id": "CAP-CLASSIFIER-1",
        "symbol": "BTCUSDT",
        "legacy_result": {"trade_mode": "SCALP", "scalp_score": 67, "mtf_bias": "NEUTRAL"},
        "entry_scenario": {
            "trade_mode": "SCALP",
            "trigger": {
                "recovery_follow_through_shadow": {
                    "would_be_action": "WOULD_ALLOW",
                    "reasons": ["SECOND_CLOSED_CANDLE_CONFIRMED"],
                }
            },
        },
        "adaptive_scalp_shadow": {
            "classification": "BEAR_RECOVERY_CAUTION",
            "advisory_action": "CAUTION_SHADOW",
            "reasons": ["BEAR_RECOVERY_NEEDS_MORE_CONFIRMATION"],
            "neutral_low_score_experiment": {
                "would_be_action": "WOULD_BLOCK",
                "gate_pass": False,
                "mtf_bias": "NEUTRAL",
                "scalp_score": 67,
                "reasons": ["SCALP_MTF_NEUTRAL", "SCALP_SCORE_65_TO_69"],
            },
            "maturity_experiment": {
                "would_be_action": "WOULD_ALLOW",
                "gate_pass": True,
                "reasons": ["RECOVERY_TRIGGER_COUNT_3_PLUS"],
            },
        },
    }
    outcome = {
        "position_id": "POS-CLASSIFIER-1",
        "symbol": "BTCUSDT",
        "trade_mode": "SCALP",
        "entry_price": 100.0,
        "quantity": 1.0,
        "gross_pnl": 0.9,
        "realized_pnl": 0.7,
        "fees": 0.2,
        "close_reason": "TRAILING_STOP",
        "entry_v2": {"capture_id": "CAP-CLASSIFIER-1"},
    }

    report = build_linked_entry_outcome_analysis("MAIN", [outcome], [capture])
    rules = report["classification_shadow_rules"]

    adaptive = rules["adaptive_scalp"]["by_trade_mode"]["SCALP"]
    assert adaptive["completed"] == 1
    assert adaptive["remaining_to_50"] == 49
    assert adaptive["samples"][0]["position_id"] == "POS-CLASSIFIER-1"
    assert adaptive["samples"][0]["classification"] == "BEAR_RECOVERY_CAUTION"
    assert adaptive["samples"][0]["net_pnl_after_fees"] == 0.7
    assert adaptive["samples"][0]["fees"] == 0.2

    neutral = rules["neutral_low_score"]["by_trade_mode"]["SCALP"]
    assert neutral["completed"] == 1
    assert neutral["by_classification"]["WOULD_BLOCK"]["net_pnl_after_fees"] == 0.7

    maturity = rules["maturity"]["by_trade_mode"]["SCALP"]
    assert maturity["completed"] == 1
    assert maturity["by_classification"]["WOULD_ALLOW"]["completed"] == 1

    recovery = rules["recovery_follow_through"]["by_trade_mode"]["SCALP"]
    assert recovery["completed"] == 1
    assert recovery["samples"][0]["would_be_action"] == "WOULD_ALLOW"


def test_neutral_low_score_would_allow_is_visible_as_control_not_counted_to_50():
    capture = {
        "capture_id": "CAP-NEUTRAL-CONTROL",
        "symbol": "ETHUSDT",
        "legacy_result": {"trade_mode": "SCALP", "scalp_score": 72, "mtf_bias": "BULLISH"},
        "adaptive_scalp_shadow": {
            "classification": "NORMAL_SCALP",
            "neutral_low_score_experiment": {
                "would_be_action": "WOULD_ALLOW",
                "reasons": ["SHADOW_CONDITION_NOT_MET"],
            },
            "maturity_experiment": {"would_be_action": "WOULD_BLOCK"},
        },
    }
    outcome = {
        "position_id": "POS-NEUTRAL-CONTROL",
        "symbol": "ETHUSDT",
        "trade_mode": "SCALP",
        "realized_pnl": -0.15,
        "fees": 0.05,
        "entry_v2": {"capture_id": "CAP-NEUTRAL-CONTROL"},
    }

    report = build_linked_entry_outcome_analysis("BYBIT", [outcome], [capture])
    neutral = report["classification_shadow_rules"]["neutral_low_score"]["by_trade_mode"]["SCALP"]

    assert neutral["completed"] == 0
    assert neutral["remaining_to_50"] == 50
    assert neutral["controls_not_counted"]["completed"] == 1
    assert neutral["controls_not_counted"]["by_action"]["WOULD_ALLOW"]["net_pnl_after_fees"] == -0.15
    assert neutral["exclusions"]["CONTROL_WOULD_ALLOW_NOT_RULE_APPLICABLE"] == 1


def test_classifier_rules_report_missing_capture_as_excluded_but_use_embedded_neutral_and_recovery():
    outcome = {
        "position_id": "POS-CLASSIFIER-FALLBACK",
        "symbol": "XRPUSDT",
        "trade_mode": "SCALP",
        "realized_pnl": 0.25,
        "fees": 0.08,
        "entry_v2": {
            "capture_id": "CAPTURE-NOT-STORED",
            "recovery_follow_through_shadow": {
                "would_be_action": "WOULD_BLOCK",
                "reasons": ["SECOND_CANDLE_FAILED_HIGHER_HIGH"],
            },
        },
        "entry_forensics": {
            "neutral_low_score_shadow": {
                "would_be_action": "WOULD_BLOCK",
                "mtf_bias": "NEUTRAL",
                "scalp_score": 66,
                "reasons": ["SCALP_MTF_NEUTRAL", "SCALP_SCORE_65_TO_69"],
            }
        },
    }

    report = build_linked_entry_outcome_analysis("OKX", [outcome], [])
    rules = report["classification_shadow_rules"]

    adaptive = rules["adaptive_scalp"]["by_trade_mode"]["SCALP"]
    assert adaptive["completed"] == 0
    assert adaptive["exclusions"]["ENTRY_CAPTURE_NOT_MATCHED"] == 1
    maturity = rules["maturity"]["by_trade_mode"]["SCALP"]
    assert maturity["completed"] == 0
    assert maturity["exclusions"]["ENTRY_CAPTURE_NOT_MATCHED"] == 1
    neutral = rules["neutral_low_score"]["by_trade_mode"]["SCALP"]
    assert neutral["completed"] == 1
    assert neutral["samples"][0]["evidence_source"] == "OUTCOME_EMBEDDED_ENTRY_CONTEXT"
    recovery = rules["recovery_follow_through"]["by_trade_mode"]["SCALP"]
    assert recovery["completed"] == 1
    assert recovery["samples"][0]["evidence_source"] == "OUTCOME_EMBEDDED_ENTRY_CONTEXT"
