from core.paper_entry_outcome_forensics import build_linked_entry_outcome_analysis


def test_main_outcome_joins_to_entry_capture_by_capture_id_and_calculates_mfe():
    capture = {
        "capture_id": "cap-main-1",
        "captured_at": "2026-11-05T08:00:00+00:00",
        "symbol": "BTCUSDT",
        "legacy_result": {
            "trade_mode": "SCALP",
            "score": 66,
            "scalp_score": 66,
            "atr": 1.5,
            "rsi5m": 38.0,
            "volume_ratio_5m": 1.4,
        },
        "entry_scenario": {
            "trade_mode": "SCALP",
            "setup_type": "REVERSAL",
            "risk": {
                "target_price": 106.0,
                "target_status": "VALID",
                "reward_risk": 2.0,
            },
        },
        "v2_decision": {
            "approved": False,
            "decision": "REJECT",
            "failed_gate": "NO_RECLAIM",
        },
    }
    outcome = {
        "position_id": "POS-MAIN-1",
        "symbol": "BTCUSDT",
        "trade_mode": "SCALP",
        "entry_price": 100.0,
        "entry_stop_loss": 97.0,
        "entry_forensics": {
            "stop_distance_source": "ENTRY_METADATA",
            "atr_percent_of_entry": 1.5,
        },
        "quantity": 1.0,
        "gross_pnl": -1.0,
        "realized_pnl": -1.3,
        "fees": 0.3,
        "highest_price": 103.5,
        "max_profit_percent": 3.5,
        "close_reason": "STOP_LOSS",
        "entry_v2": {"capture_id": "cap-main-1"},
        "regime": {"market": "BULLISH"},
    }

    result = build_linked_entry_outcome_analysis("MAIN", [outcome], [capture])

    assert result["coverage"]["matched_closed_trades"] == 1
    assert result["coverage"]["unmatched_outcomes"] == 0
    assert result["overall"]["losses"] == 1
    assert result["overall"]["net_pnl_after_fees"] == -1.3
    assert result["overall"]["average_expected_rr"] == 2.0
    assert result["overall"]["average_realized_r_multiple_net"] == -0.4333
    assert result["overall"]["losers_with_positive_net_favorable_excursion"] == 1
    assert result["losers_with_positive_net_favorable_excursion"][0]["net_mfe"] == 3.2
    assert result["by_entry_v2_shadow_approval"]["FALSE"]["closed_trades"] == 1
    assert result["worst_trades"][0]["entry_v2_failed_gate_shadow"] == "NO_RECLAIM"


def test_hosted_lab_outcome_joins_to_capture_by_position_id():
    capture = {
        "capture_id": "lab-capture-1",
        "position_id": "POS-BYBIT-1",
        "symbol": "ETHUSDT",
        "candidate": {
            "symbol": "ETHUSDT",
            "trade_mode": "SWING",
            "score": 82,
            "entry_price": 50.0,
            "stop_loss": 49.5,
            "market_data_source": "BYBIT",
        },
        "legacy_result": {"atr": 0.25, "rsi5m": 42.0},
        "entry_economics": {
            "reward_risk": 1.5,
            "risk_percent": 1.0,
            "net_reward_percent": 1.3,
        },
        "v2_decision": {"approved": True, "decision": "APPROVE"},
    }
    outcome = {
        "position_id": "POS-BYBIT-1",
        "symbol": "ETHUSDT",
        "trade_mode": "SWING",
        "entry_price": 50.0,
        "entry_stop_loss": 49.4,
        "entry_forensics": {"stop_distance_source": "POSITION_CURRENT_STOP_FALLBACK"},
        "quantity": 10.0,
        "gross_pnl": -0.5,
        "realized_pnl": -0.6,
        "fees": 0.1,
        "highest_price": 50.3,
        "close_reason": "STOP_LOSS",
    }

    result = build_linked_entry_outcome_analysis("BYBIT", [outcome], [capture])

    assert result["coverage"]["matched_closed_trades"] == 1
    assert result["by_trade_mode"]["SWING"]["closed_trades"] == 1
    assert result["overall"]["average_stop_atr_multiple"] == 2.0
    assert result["overall"]["average_expected_net_rr_after_fees"] == 1.3
    assert result["overall"]["losers_with_positive_net_favorable_excursion"] == 1


def test_unmatched_outcome_is_reported_and_never_filled_from_unrelated_capture():
    outcome = {
        "position_id": "POS-UNKNOWN",
        "symbol": "XRPUSDT",
        "trade_mode": "SCALP",
        "realized_pnl": -0.4,
    }
    unrelated_capture = {
        "capture_id": "capture-other",
        "position_id": "POS-OTHER",
        "symbol": "BTCUSDT",
    }

    result = build_linked_entry_outcome_analysis("OKX", [outcome], [unrelated_capture])

    assert result["coverage"]["matched_closed_trades"] == 0
    assert result["coverage"]["unmatched_outcomes"] == 1
    assert result["overall"]["closed_trades"] == 0
    assert result["coverage"]["unmatched_entry_captures"] == 1


def test_forensics_rejects_unsupported_venue():
    try:
        build_linked_entry_outcome_analysis("BINANCE", [], [])
    except ValueError as exc:
        assert "unsupported Paper venue" in str(exc)
    else:
        raise AssertionError("unsupported venue should be rejected")
