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
    assert result["by_trade_mode_and_failed_gate"]["SCALP"]["NO_RECLAIM"]["closed_trades"] == 1
    assert result["by_trade_mode_and_score_band"]["SCALP"]["65_69"]["closed_trades"] == 1
    assert result["by_market_regime"]["BULLISH"]["closed_trades"] == 1
    assert result["by_market_regime_source"]["OUTCOME_REGIME"]["closed_trades"] == 1


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
    assert result["overall"]["paired_expected_rr_sample_count"] == 1
    assert result["overall"]["paired_average_expected_rr"] == 1.5
    assert result["overall"]["paired_average_expected_net_rr_after_fees"] == 1.3
    assert result["overall"]["average_fees_as_r_multiple"] == 0.02
    assert result["by_trade_mode_and_score_band"]["SWING"]["80_84"]["closed_trades"] == 1
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
    assert result["coverage"]["unmatched_entry_captures"] == 1
    assert result["coverage"]["outcome_context_fallback_trades"] == 0
    assert result["coverage"]["unmatched_outcomes_without_entry_context"] == 1
    assert result["coverage"]["analyzed_closed_trades"] == 1
    assert result["coverage"]["decision_evidence_coverage_percent"] == 0.0
    # The realized PnL belongs to this closed outcome and is valid even when
    # its entry-decision evidence is missing. No unrelated capture is reused.
    assert result["overall"]["closed_trades"] == 1
    assert result["overall"]["net_pnl_after_fees"] == -0.4
    assert result["worst_trades"][0]["position_id"] == "POS-UNKNOWN"
    assert result["worst_trades"][0]["decision_evidence_source"] == "OUTCOME_ONLY"


def test_classification_shadow_links_all_four_rules_to_unique_closed_paper_outcomes():
    capture = {
        "capture_id": "CAP-CLASS-1",
        "captured_at": "2026-11-11T08:00:00+00:00",
        "symbol": "BTCUSDT",
        "legacy_result": {
            "trade_mode": "SCALP",
            "scalp_score": 68,
            "score": 68,
            "scalp_signal": "BUY",
            "mtf_bias": "NEUTRAL",
            "mtf_timeframe_bias": {
                "5m": "BULLISH", "15m": "BEARISH", "1h": "BEARISH", "4h": "BEARISH"
            },
            "scalp_recovery_confirmation": True,
            "scalp_confirmed_reversal": True,
            "scalp_recovery_trigger_count": 3,
            "scalp_recovery_trigger_reasons": [
                "5M_RSI_RISING", "5M_PRICE_RECOVERY", "5M_BULLISH_BODY"
            ],
            "volume_ratio_5m": 1.2,
            "pattern_confirmed": True,
            "pattern": "BULLISH_ENGULFING",
        },
        "entry_scenario": {
            "trade_mode": "SCALP",
            "trigger": {
                "recovery_follow_through_shadow": {
                    "shadow_only": True,
                    "applicable": True,
                    "available": True,
                    "would_be_action": "WOULD_ALLOW",
                }
            },
        },
        "adaptive_scalp_shadow": {
            "classification": "BEAR_RECOVERY_STRONG",
            "recovery_trigger_count": 3,
            "maturity_experiment": {
                "would_be_action": "WOULD_ALLOW",
                "shadow_only": True,
            },
            "neutral_low_score_experiment": {
                "would_be_action": "WOULD_BLOCK",
                "scalp_score": 68,
                "mtf_bias": "NEUTRAL",
                "shadow_only": True,
            },
        },
        "v2_decision": {"trade_mode": "SCALP"},
    }
    outcome = {
        "position_id": "POS-CLASS-1",
        "symbol": "BTCUSDT",
        "status": "CLOSED",
        "closed_at_utc": "2026-11-11T08:20:00+00:00",
        "trade_mode": "SCALP",
        "entry_v2": {"capture_id": "CAP-CLASS-1"},
        "gross_pnl": 0.35,
        "realized_pnl": 0.25,
        "fees": 0.10,
        "close_reason": "TRAILING_STOP",
    }

    result = build_linked_entry_outcome_analysis("MAIN", [outcome], [capture])
    report = result["classification_shadow"]

    expected = {
        "adaptive_scalp": "BEAR_RECOVERY_STRONG",
        "neutral_low_score": "WOULD_BLOCK",
        "maturity": "WOULD_ALLOW",
        "recovery_follow_through": "WOULD_ALLOW",
    }
    for rule, label in expected.items():
        cohort = report["rules"][rule]["by_trade_mode"]["SCALP"]
        assert cohort["completed"] == 1
        assert cohort["remaining"] == 49
        assert cohort["excluded_positions"] == 0
        assert cohort["samples"][0]["position_id"] == "POS-CLASS-1"
        assert cohort["samples"][0]["classification"] == label
        # realized_pnl is already net of the recorded 0.10 fee.
        assert cohort["samples"][0]["net_pnl_after_fees"] == 0.25
        assert cohort["samples"][0]["fees"] == 0.10
        assert cohort["by_classification"][label]["net_pnl_after_fees"] == 0.25

    assert report["rules"]["adaptive_scalp"]["by_trade_mode"]["SWING"]["applicable"] is False
    assert report["accounting"].find("without subtracting fees a second time") >= 0


def test_classification_shadow_excludes_unavailable_recovery_observations():
    outcome = {
        "position_id": "POS-RECOVERY-NA",
        "symbol": "ADAUSDT",
        "status": "CLOSED",
        "trade_mode": "SCALP",
        "realized_pnl": -0.2,
        "fees": 0.05,
        "entry_v2": {"recovery_follow_through_shadow": {
            "applicable": True,
            "available": False,
            "would_be_action": "INSUFFICIENT_DATA",
        }},
    }
    report = build_linked_entry_outcome_analysis("OKX", [outcome], [])["classification_shadow"]
    cohort = report["rules"]["recovery_follow_through"]["by_trade_mode"]["SCALP"]

    assert cohort["completed"] == 0
    assert cohort["remaining"] == 50
    assert cohort["excluded_positions"] == 1
    assert cohort["exclusion_reasons"] == {"INSUFFICIENT_DATA": 1}
    assert cohort["samples"] == []


def test_forensics_rejects_unsupported_venue():
    try:
        build_linked_entry_outcome_analysis("BINANCE", [], [])
    except ValueError as exc:
        assert "unsupported Paper venue" in str(exc)
    else:
        raise AssertionError("unsupported venue should be rejected")



def test_shadow_main_forensics_reads_only_captures_referenced_by_closed_outcomes(monkeypatch):
    from types import SimpleNamespace
    import shadow_main

    class FakeStore:
        def __init__(self, outcomes=None, captures=None):
            self.outcomes = list(outcomes or [])
            self.captures = list(captures or [])
            self.last_error = None
            self.requested = None

        def read_time_range(self, timestamp_field, _start, _end):
            assert timestamp_field == "closed_at_utc"
            return list(self.outcomes)

        def read_by_identity_keys(self, keys):
            self.requested = set(keys)
            return [
                row for row in self.captures
                if row.get("capture_id") in self.requested
            ]

        def read_by_payload_values(self, field, values):
            assert field == "position_id"
            self.requested = set(values)
            return [
                row for row in self.captures
                if row.get("position_id") in self.requested
            ]

        def read_all(self):
            raise AssertionError("forensics must never load the full capture history")

    main_outcome = {
        "position_id": "POS-MAIN-1",
        "symbol": "BTCUSDT",
        "trade_mode": "SCALP",
        "entry_price": 100.0,
        "entry_stop_loss": 99.0,
        "entry_forensics": {"stop_distance_source": "ENTRY_METADATA"},
        "quantity": 1.0,
        "gross_pnl": 0.2,
        "realized_pnl": 0.0,
        "fees": 0.2,
        "highest_price": 100.5,
        "close_reason": "STOP_LOSS",
        "entry_v2": {"capture_id": "CAP-MAIN-1"},
    }
    main_capture = {
        "capture_id": "CAP-MAIN-1",
        "symbol": "BTCUSDT",
        "legacy_result": {"trade_mode": "SCALP", "scalp_score": 66, "atr": 0.5},
        "entry_scenario": {"trade_mode": "SCALP", "risk": {"reward_risk": 2.0}},
        "v2_decision": {"approved": True, "decision": "APPROVE"},
    }
    bybit_outcome = {
        "position_id": "POS-BYBIT-1",
        "symbol": "ETHUSDT",
        "trade_mode": "SWING",
        "entry_price": 50.0,
        "entry_stop_loss": 49.5,
        "entry_forensics": {"stop_distance_source": "POSITION_CURRENT_STOP_FALLBACK"},
        "quantity": 1.0,
        "gross_pnl": -0.6,
        "realized_pnl": -0.8,
        "fees": 0.2,
        "highest_price": 50.2,
        "close_reason": "STOP_LOSS",
    }
    bybit_capture = {
        "capture_id": "CAP-BYBIT-1",
        "position_id": "POS-BYBIT-1",
        "symbol": "ETHUSDT",
        "candidate": {
            "symbol": "ETHUSDT",
            "trade_mode": "SWING",
            "score": 81,
            "entry_price": 50.0,
            "stop_loss": 49.5,
        },
        "legacy_result": {"atr": 0.25},
        "entry_economics": {
            "reward_risk": 1.5,
            "risk_percent": 1.0,
            "net_reward_percent": 1.2,
        },
    }
    okx_outcome = {
        "position_id": "POS-OKX-1",
        "symbol": "XRPUSDT",
        "trade_mode": "SWING",
        "entry_price": 1.0,
        "entry_stop_loss": 0.99,
        "entry_forensics": {"stop_distance_source": "POSITION_CURRENT_STOP_FALLBACK"},
        "quantity": 1.0,
        "gross_pnl": 0.3,
        "realized_pnl": 0.1,
        "fees": 0.2,
        "highest_price": 1.4,
        "close_reason": "TRAILING_STOP",
    }
    okx_capture = {
        "capture_id": "CAP-OKX-1",
        "position_id": "POS-OKX-1",
        "symbol": "XRPUSDT",
        "candidate": {
            "symbol": "XRPUSDT",
            "trade_mode": "SWING",
            "score": 84,
            "entry_price": 1.0,
            "stop_loss": 0.99,
        },
        "legacy_result": {"atr": 0.005},
        "entry_economics": {
            "reward_risk": 1.8,
            "risk_percent": 1.0,
            "net_reward_percent": 1.5,
        },
    }

    main_outcome_store = FakeStore([main_outcome])
    main_capture_store = FakeStore(captures=[main_capture, {"capture_id": "UNRELATED-LARGE-CAPTURE"}])
    bybit = SimpleNamespace(
        outcomes=FakeStore([bybit_outcome]),
        entry_captures=FakeStore(captures=[bybit_capture, {"capture_id": "UNRELATED", "position_id": "POS-OTHER"}]),
    )
    okx = SimpleNamespace(
        outcomes=FakeStore([okx_outcome]),
        entry_captures=FakeStore(captures=[okx_capture]),
    )

    monkeypatch.setattr(shadow_main, "_paper_outcome_store", main_outcome_store)
    monkeypatch.setattr(
        shadow_main,
        "_entry_v2_runtime_capture",
        SimpleNamespace(capture_store=main_capture_store),
    )
    monkeypatch.setattr(
        shadow_main,
        "_hosted_paper_lab_runner",
        SimpleNamespace(labs={"BYBIT": bybit, "OKX": okx}),
    )
    monkeypatch.setattr(
        shadow_main,
        "_paper_forensics_time_range",
        lambda: ("2026-08-08T00:00:00+00:00", "2026-11-06T00:00:00+00:00"),
    )

    report = shadow_main._build_linked_entry_outcome_forensics()

    assert report["available"] is True
    assert main_capture_store.requested == {"CAP-MAIN-1"}
    assert bybit.entry_captures.requested == {"POS-BYBIT-1"}
    assert okx.entry_captures.requested == {"POS-OKX-1"}
    assert report["venues"]["MAIN"]["coverage"]["matched_closed_trades"] == 1
    assert report["venues"]["BYBIT"]["coverage"]["matched_closed_trades"] == 1
    assert report["venues"]["OKX"]["coverage"]["matched_closed_trades"] == 1



def test_forensics_reports_peak_gain_bands_and_profit_protection_state():
    outcomes = [
        {
            "position_id": "POS-PROTECTED",
            "symbol": "ETHUSDT",
            "trade_mode": "SWING",
            "entry_price": 100.0,
            "entry_stop_loss": 98.0,
            "quantity": 1.0,
            "gross_pnl": 0.8,
            "realized_pnl": 0.6,
            "fees": 0.2,
            "highest_price": 101.0,
            "max_profit_percent": 1.0,
            "close_reason": "TRAILING_STOP",
            "exit_protection": {
                "paper_profit_protection": True,
                "net_floor_shadow_trial": {
                    "version": "PAPER_PROFIT_PROTECTION_NET_FLOOR_V1",
                    "status": "OBSERVING",
                    "triggered": False,
                },
                "paper_profit_protection_detail": {
                    "current_gain_percent": 0.65,
                    "peak_gain_percent": 1.0,
                    "retrace_percent": 0.35,
                    "min_gain_percent": 0.6,
                    "min_retrace_percent": 0.35,
                },
            },
        },
        {
            "position_id": "POS-UNPROTECTED",
            "symbol": "BTCUSDT",
            "trade_mode": "SWING",
            "entry_price": 100.0,
            "entry_stop_loss": 98.0,
            "quantity": 1.0,
            "gross_pnl": -0.4,
            "realized_pnl": -0.6,
            "fees": 0.2,
            "highest_price": 100.35,
            "max_profit_percent": 0.35,
            "close_reason": "STOP_LOSS",
            "exit_protection": {
                "paper_profit_protection": False,
                "paper_profit_protection_detail": None,
                "net_floor_shadow_trial": {
                    "version": "PAPER_PROFIT_PROTECTION_NET_FLOOR_V1",
                    "status": "TRIGGERED",
                    "triggered": True,
                    "exit_price": 100.40,
                    "current_gain_percent": 0.40,
                    "peak_gain_percent": 0.80,
                    "retrace_percent": 0.397,
                    "gross_pnl_estimate": 0.40,
                    "entry_fee_paid": 0.10,
                    "estimated_exit_fee": 0.1004,
                    "net_pnl_estimate_after_fees": 0.1996,
                },
            },
        },
    ]
    captures = [
        {
            "capture_id": "CAP-PROTECTED",
            "position_id": "POS-PROTECTED",
            "candidate": {"symbol": "ETHUSDT", "trade_mode": "SWING", "score": 82},
            "entry_economics": {"reward_risk": 1.5, "net_reward_percent": 1.2},
            "legacy_result": {"atr": 1.0},
        },
        {
            "capture_id": "CAP-UNPROTECTED",
            "position_id": "POS-UNPROTECTED",
            "candidate": {"symbol": "BTCUSDT", "trade_mode": "SWING", "score": 83},
            "entry_economics": {"reward_risk": 1.5, "net_reward_percent": 1.2},
            "legacy_result": {"atr": 1.0},
        },
    ]

    report = build_linked_entry_outcome_analysis("BYBIT", outcomes, captures)

    assert report["coverage"]["matched_closed_trades"] == 2
    assert report["overall"]["paper_profit_protection_observed_trades"] == 2
    assert report["overall"]["paper_profit_protection_triggered_trades"] == 1
    assert report["overall"]["paper_profit_protection_trigger_rate_percent"] == 50.0
    assert report["by_trade_mode_and_peak_gain_band"]["SWING"]["1_00_TO_2_00"]["closed_trades"] == 1
    assert report["by_trade_mode_and_peak_gain_band"]["SWING"]["0_20_TO_0_40"]["closed_trades"] == 1
    assert report["by_trade_mode_and_paper_profit_protection"]["SWING"]["TRUE"]["closed_trades"] == 1
    assert report["by_paper_profit_protection_triggered"]["FALSE"]["closed_trades"] == 1
    assert report["worst_trades"][0]["paper_profit_protection_triggered"] is False
    assert report["best_trades"][0]["paper_profit_protection_detail"]["min_gain_percent"] == 0.6
    assert report["overall"]["net_floor_shadow_observed_trades"] == 2
    assert report["overall"]["net_floor_shadow_triggered_trades"] == 1
    assert report["overall"]["net_floor_shadow_trigger_rate_percent"] == 50.0
    assert report["overall"]["net_floor_shadow_estimated_net_pnl_on_triggered_trades"] == 0.1996
    assert report["overall"]["actual_net_pnl_on_shadow_triggered_trades"] == -0.6
    assert round(report["overall"]["net_floor_shadow_delta_vs_actual_on_triggered_trades"], 4) == 0.7996
    assert report["by_trade_mode_and_profit_protection_shadow_status"]["SWING"]["TRIGGERED"]["closed_trades"] == 1
    assert report["worst_trades"][0]["profit_protection_shadow_triggered"] is True


def test_missing_capture_uses_embedded_outcome_entry_context_without_claiming_capture_match():
    outcome = {
        "position_id": "POS-OUTCOME-FALLBACK",
        "symbol": "BTCUSDT",
        "trade_mode": "SCALP",
        "entry_price": 100.0,
        "entry_stop_loss": 99.0,
        "quantity": 1.0,
        "gross_pnl": -0.1,
        "realized_pnl": -0.3,
        "fees": 0.2,
        "highest_price": 100.2,
        "max_profit_percent": 0.2,
        "close_reason": "STOP_LOSS",
        "entry_forensics": {
            "stop_distance_source": "ENTRY_METADATA",
            "mtf_bias": "BEARISH",
            "mtf_net": -24,
            "volume_ratio_5m": 0.8,
        },
        "entry_economics": {
            "reward_risk": 1.4,
            "risk_percent": 1.0,
            "net_reward_percent": 1.1,
        },
        "entry_v2": {
            "capture_id": "CAPTURE-NOT-PERSISTED",
            "decision": "REJECT",
            "approved": False,
            "failed_gate": "SELLER_PRESSURE_NOT_INVALIDATED",
            "target_price": 101.4,
        },
        "strategy": {
            "score": 65,
            "scalp_score": 65,
            "rsi5m": 52,
            "atr": 0.5,
            "mtf_bias": "BEARISH",
            "mtf_net": -24,
            "volume_ratio_5m": 0.8,
        },
        "regime": {
            "market": None,
            "symbol": "BEAR",
        },
    }

    report = build_linked_entry_outcome_analysis("MAIN", [outcome], [])

    coverage = report["coverage"]
    assert coverage["matched_closed_trades"] == 0
    assert coverage["matched_percent_of_outcomes"] == 0.0
    assert coverage["unmatched_outcomes"] == 1
    assert coverage["outcome_context_fallback_trades"] == 1
    assert coverage["unmatched_outcomes_without_entry_context"] == 0
    assert coverage["analyzed_closed_trades"] == 1
    assert coverage["analyzed_percent_of_outcomes"] == 100.0
    assert coverage["decision_evidence_covered_trades"] == 1
    assert coverage["decision_evidence_coverage_percent"] == 100.0

    assert report["overall"]["closed_trades"] == 1
    assert report["overall"]["net_pnl_after_fees"] == -0.3
    assert report["overall"]["average_expected_rr"] == 1.4
    assert report["overall"]["average_expected_net_rr_after_fees"] == 1.1
    assert report["by_trade_mode_and_failed_gate"]["SCALP"]["SELLER_PRESSURE_NOT_INVALIDATED"]["closed_trades"] == 1
    assert report["by_trade_mode_and_score_band"]["SCALP"]["65_69"]["closed_trades"] == 1
    assert report["by_trade_mode_and_mtf_bias"]["SCALP"]["BEARISH"]["closed_trades"] == 1
    assert report["by_trade_mode_and_mtf_net_band"]["SCALP"]["BELOW_-20"]["closed_trades"] == 1
    assert report["by_trade_mode_and_volume_band"]["SCALP"]["BELOW_1_0"]["closed_trades"] == 1
    assert report["by_trade_mode_and_rsi5m_band"]["SCALP"]["49_TO_60"]["closed_trades"] == 1

    worst = report["worst_trades"][0]
    assert worst["position_id"] == "POS-OUTCOME-FALLBACK"
    assert worst["capture_id"] == "CAPTURE-NOT-PERSISTED"
    assert worst["capture_matched"] is False
    assert worst["decision_evidence_source"] == "OUTCOME_EMBEDDED_ENTRY_CONTEXT"
    assert worst["market_regime"] == "UNKNOWN"
    assert worst["symbol_regime"] == "BEAR"
    assert worst["mtf_bias"] == "BEARISH"
    assert worst["mtf_net"] == -24


def test_outcome_without_embedded_entry_context_still_counts_in_actual_results():
    outcome = {
        "position_id": "POS-OUTCOME-ONLY",
        "symbol": "ETHUSDT",
        "trade_mode": "SWING",
        "entry_price": 50.0,
        "quantity": 2.0,
        "gross_pnl": 0.2,
        "realized_pnl": 0.0,
        "fees": 0.2,
        "close_reason": "TIME_EXIT",
    }

    report = build_linked_entry_outcome_analysis("OKX", [outcome], [])

    assert report["coverage"]["matched_closed_trades"] == 0
    assert report["coverage"]["outcome_context_fallback_trades"] == 0
    assert report["coverage"]["unmatched_outcomes_without_entry_context"] == 1
    assert report["coverage"]["analyzed_closed_trades"] == 1
    assert report["coverage"]["decision_evidence_coverage_percent"] == 0.0
    assert report["overall"]["closed_trades"] == 1
    assert report["overall"]["net_pnl_after_fees"] == 0.0
    assert report["by_trade_mode"]["SWING"]["closed_trades"] == 1
    assert report["worst_trades"][0]["decision_evidence_source"] == "OUTCOME_ONLY"
