from core.paper_precalibration_shadow import (
    TRIAL_NAME,
    build_precalibration_decision_record,
    build_precalibration_shadow_report,
    candidate_identity,
)


def _brain(allowed=True, reason="CONFIRMED_ENTRY", selective=""):
    return {
        "brain_action": "BUY" if allowed else "HOLD",
        "brain_reason": reason,
        "allowed": allowed,
        "context": {"selective_v2_veto": selective or None},
    }


def _economics(approved=True):
    return {
        "approved": approved,
        "reason": "APPROVED" if approved else "NET_REWARD_AFTER_FEES_TOO_LOW",
        "round_trip_fee_percent": 0.2,
        "net_reward_percent": 0.45 if approved else 0.10,
    }


def _decision(**overrides):
    values = {
        "candidate_id": f"{TRIAL_NAME}:TRXUSDT:SCALP:1794213900000",
        "symbol": "TRXUSDT",
        "candle_open_time_ms": 1794213900000,
        "captured_at_utc": "2026-11-09T08:45:00+00:00",
        "prior_score": 70,
        "current_score": 52,
        "entry_price": 0.30,
        "stop_price": 0.294,
        "target_price": 0.312,
        "target_status": "VALID",
        "reward_risk": 2.0,
        "fee_rate_per_side": 0.001,
        "brain_record": _brain(),
        "economics": _economics(),
        "entry_v2_capture_id": "entry-v2-123",
        "entry_v2_decision": "REJECT",
        "entry_v2_failed_gate": "SOME_ADVISORY_GATE",
        "existing_position": False,
        "market_regime": "BEAR",
        "symbol_regime": "BEAR",
    }
    values.update(overrides)
    return build_precalibration_decision_record(**values)


def test_candidate_identity_deduplicates_same_closed_candle_and_separates_new_bar():
    same_a = candidate_identity("trxusdt", 1794213900000)
    same_b = candidate_identity("TRXUSDT", "1794213900000")
    next_bar = candidate_identity("TRXUSDT", 1794214200000)

    assert same_a == same_b
    assert same_a == f"{TRIAL_NAME}:TRXUSDT:SCALP:1794213900000"
    assert next_bar != same_a
    assert candidate_identity("TRXUSDT", None) is None


def test_candidate_is_watch_eligible_only_after_brain_and_fee_economics_pass():
    row = _decision()

    assert row["disposition"] == "BRAIN_ECONOMICS_QUALIFIED_WATCH"
    assert row["risk_authority"] == "NOT_SIMULATED"
    assert row["trade_manager_authority"] == "NOT_SIMULATED"
    assert row["execution_authority"] == "NOT_SIMULATED"
    assert row["brain_allowed"] is True
    assert row["target_status"] == "VALID"
    assert row["estimated_round_trip_fee_percent"] == 0.2
    assert row["score_delta"] == 18
    assert row["mode"] == "PAPER_ONLY"


def test_candidate_blocked_by_brain_is_not_price_path_tracked():
    row = _decision(brain_record=_brain(False, "BEAR_SELLER_FAILURE_NOT_CONFIRMED"))

    assert row["disposition"] == "BRAIN_REJECTED"
    assert row["brain_reason"] == "BEAR_SELLER_FAILURE_NOT_CONFIRMED"


def test_selective_entry_v2_veto_takes_precedence_over_watch_eligibility():
    row = _decision(
        brain_record=_brain(False, "V2_SELLER_PRESSURE_RSI_PRESSURE", "V2_SELLER_PRESSURE_RSI_PRESSURE")
    )

    assert row["disposition"] == "BRAIN_SELECTIVE_VETO"
    assert row["selective_v2_veto"] == "V2_SELLER_PRESSURE_RSI_PRESSURE"


def test_invalid_target_or_unprofitable_net_reward_is_not_watched():
    no_target = _decision(target_status="NO_TARGET_MEETS_RR", target_price=None)
    weak_reward = _decision(economics=_economics(False))

    assert no_target["disposition"] == "NO_VALID_TARGET"
    assert weak_reward["disposition"] == "ENTRY_ECONOMICS_REJECTED"


def test_existing_position_is_not_treated_as_a_recovered_opportunity():
    row = _decision(existing_position=True)

    assert row["disposition"] == "SKIPPED_EXISTING_POSITION"


def test_report_excludes_ambiguous_and_data_gap_from_decisive_results():
    rows = [
        _decision(candidate_id="candidate-a"),
        {
            "record_type": "START",
            "record_id": "candidate-a:START",
            "candidate_id": "candidate-a",
            "symbol": "TRXUSDT",
            "status": "OBSERVING",
        },
        {
            "record_type": "FINAL",
            "record_id": "candidate-a:FINAL",
            "candidate_id": "candidate-a",
            "symbol": "TRXUSDT",
            "status": "TARGET_HIT",
            "net_return_percent_after_estimated_fees": 0.8,
            "net_r_multiple_after_estimated_fees": 1.2,
        },
        {
            "record_type": "START",
            "record_id": "candidate-b:START",
            "candidate_id": "candidate-b",
            "symbol": "TRXUSDT",
            "status": "OBSERVING",
        },
        {
            "record_type": "FINAL",
            "record_id": "candidate-b:FINAL",
            "candidate_id": "candidate-b",
            "symbol": "TRXUSDT",
            "status": "STOP_HIT",
            "net_return_percent_after_estimated_fees": -0.4,
            "net_r_multiple_after_estimated_fees": -0.7,
        },
        {
            "record_type": "START",
            "record_id": "candidate-c:START",
            "candidate_id": "candidate-c",
            "symbol": "TRXUSDT",
            "status": "OBSERVING",
        },
        {
            "record_type": "FINAL",
            "record_id": "candidate-c:FINAL",
            "candidate_id": "candidate-c",
            "symbol": "TRXUSDT",
            "status": "AMBIGUOUS_SAME_CANDLE",
            "net_return_percent_after_estimated_fees": None,
        },
        {
            "record_type": "START",
            "record_id": "candidate-d:START",
            "candidate_id": "candidate-d",
            "symbol": "TRXUSDT",
            "status": "OBSERVING",
        },
        {
            "record_type": "FINAL",
            "record_id": "candidate-d:FINAL",
            "candidate_id": "candidate-d",
            "symbol": "TRXUSDT",
            "status": "DATA_GAP",
            "net_return_percent_after_estimated_fees": None,
        },
    ]

    report = build_precalibration_shadow_report(rows)

    assert report["unique_candidate_count"] == 4
    assert report["watch_started"] == 4
    assert report["watch_completed"] == 4
    assert report["decisive_outcomes"] == 2
    assert report["wins"] == 1
    assert report["losses"] == 1
    assert report["net_profit_factor_after_estimated_fees"] == 2.0
    assert report["sum_net_return_percent_after_estimated_fees"] == 0.4
    assert report["outcomes"]["AMBIGUOUS_SAME_CANDLE"] == 1
    assert report["outcomes"]["DATA_GAP"] == 1
    assert report["interpretation"]["trading_logic_changed"] is False


def test_preflight_data_ticker_and_cooldown_rejections_precede_brain():
    stale_data = _decision(preflight_rejection="STALE_ENTRY_DATA")
    stale_ticker = _decision(preflight_rejection="STALE_TICKER")
    cooldown = _decision(
        preflight_rejection="LOSS_COOLDOWN",
        preflight_details={"remaining_seconds": 125.0},
    )

    assert stale_data["disposition"] == "STALE_ENTRY_DATA"
    assert stale_data["brain_reason"] == "CONFIRMED_ENTRY"
    assert stale_ticker["disposition"] == "STALE_TICKER"
    assert cooldown["disposition"] == "LOSS_COOLDOWN"
    assert cooldown["preflight_details"]["remaining_seconds"] == 125.0


def test_report_counts_watch_eligible_as_a_disposition():
    rows = [
        {
            "record_type": "START",
            "record_id": "eligible:START",
            "candidate_id": "eligible",
            "symbol": "TRXUSDT",
            "status": "OBSERVING",
            "disposition": "BRAIN_ECONOMICS_QUALIFIED_WATCH",
        }
    ]

    report = build_precalibration_shadow_report(rows)

    assert report["unique_candidate_count"] == 1
    assert report["dispositions"]["BRAIN_ECONOMICS_QUALIFIED_WATCH"] == 1
    assert "not simulated" in report["interpretation"]["unmodeled_authorities"].lower()
    assert report["watch_active"] == 1


def test_preflight_rejection_precedes_brain_and_existing_position_only_applies_without_earlier_guard():
    btc_crash = _decision(
        preflight_rejection="BTC_CRASH_GUARD",
        existing_position=True,
    )
    stale_data = _decision(
        preflight_rejection="STALE_ENTRY_DATA",
        brain_record=_brain(True),
    )

    assert btc_crash["disposition"] == "BTC_CRASH_GUARD"
    assert stale_data["disposition"] == "STALE_ENTRY_DATA"


def test_market_data_rebase_is_excluded_only_after_brain_and_fee_economics_pass():
    rebased = _decision(
        market_data_rejection="MARKET_DATA_REBASE_NOT_MODELED",
        market_data_details={
            "market_data_source": "BYBIT",
            "reason": "BINANCE_ENTRY_STOP_REBASED_BUT_PIVOT_TARGET_NOT_RECOMPUTED_ON_BINANCE_CANDLES",
        },
    )
    brain_rejected = _decision(
        brain_record=_brain(False, "BEAR_RECOVERY_NOT_CONFIRMED"),
        market_data_rejection="MARKET_DATA_REBASE_NOT_MODELED",
    )
    economics_rejected = _decision(
        economics=_economics(False),
        market_data_rejection="MARKET_DATA_REBASE_NOT_MODELED",
    )

    assert rebased["disposition"] == "MARKET_DATA_REBASE_NOT_MODELED"
    assert rebased["market_data_details"]["market_data_source"] == "BYBIT"
    assert brain_rejected["disposition"] == "BRAIN_REJECTED"
    assert economics_rejected["disposition"] == "ENTRY_ECONOMICS_REJECTED"
