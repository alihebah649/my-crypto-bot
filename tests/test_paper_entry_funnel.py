from core.paper_entry_funnel import (
    build_entry_funnel_record,
    build_entry_funnel_report,
)


def _brain_record(capture_id="capture-1", allowed=True, mode="SCALP", at="2026-11-09T08:02:00+00:00"):
    return {
        "capture_id": capture_id,
        "symbol": "BTCUSDT",
        "trade_mode": mode,
        "stage": "ENTRY_GATE",
        "strategy_action": "BUY",
        "strategy_score": 65,
        "brain_action": "BUY" if allowed else "HOLD",
        "brain_reason": "CONFIRMED_ENTRY" if allowed else "BEAR_SWING_DISABLED",
        "allowed": allowed,
        "context": {"entry_v2_shadow": {"captured_at": at}},
    }


def test_final_record_preserves_brain_decision_and_attaches_final_outcome():
    result = build_entry_funnel_record(
        _brain_record(),
        symbol="BTCUSDT",
        trade_mode="SCALP",
        capture_id="capture-1",
        captured_at="2026-11-09T08:02:00+00:00",
        strategy_action="BUY",
        strategy_score=65,
        final_status="POSITION_COMMITTED",
        failed_gate=None,
        execution_attempted=True,
        position_opened=True,
        details={"position_id": "PAPER-1"},
        recorded_at_utc="2026-11-09T08:03:00+00:00",
    )

    assert result["stage"] == "ENTRY_GATE"
    assert result["allowed"] is True
    assert result["brain_reason"] == "CONFIRMED_ENTRY"
    assert result["final_decision"]["status"] == "POSITION_COMMITTED"
    assert result["final_decision"]["position_opened"] is True
    assert result["final_decision"]["details"]["position_id"] == "PAPER-1"


def test_pre_brain_rejection_is_recorded_without_fabricating_brain_approval():
    result = build_entry_funnel_record(
        None,
        symbol="ETHUSDT",
        trade_mode="SWING",
        capture_id="capture-prebrain",
        captured_at="2026-11-09T08:02:00+00:00",
        strategy_action="BUY",
        strategy_score=81,
        final_status="REJECTED_LOSS_COOLDOWN",
        failed_gate="LOSS_COOLDOWN",
        execution_attempted=False,
        position_opened=False,
    )

    assert result["stage"] == "ENTRY_PIPELINE"
    assert result["allowed"] is None
    assert result["brain_action"] == "NOT_EVALUATED"
    assert result["final_decision"]["failed_gate"] == "LOSS_COOLDOWN"


def test_report_counts_daily_mode_and_final_funnel_stages():
    records = [
        build_entry_funnel_record(
            _brain_record("a", True, "SCALP"),
            symbol="BTCUSDT", trade_mode="SCALP", capture_id="a",
            captured_at="2026-11-09T08:02:00+00:00", strategy_action="BUY",
            strategy_score=65, final_status="POSITION_COMMITTED",
            failed_gate=None, execution_attempted=True, position_opened=True,
        ),
        build_entry_funnel_record(
            _brain_record("b", False, "SWING"),
            symbol="ETHUSDT", trade_mode="SWING", capture_id="b",
            captured_at="2026-11-09T08:03:00+00:00", strategy_action="BUY",
            strategy_score=81, final_status="REJECTED_BRAIN_AUTHORITY",
            failed_gate="BEAR_SWING_DISABLED", execution_attempted=False, position_opened=False,
        ),
        build_entry_funnel_record(
            None,
            symbol="SOLUSDT", trade_mode="SCALP", capture_id="c",
            captured_at="2026-11-09T08:04:00+00:00", strategy_action="BUY",
            strategy_score=65, final_status="REJECTED_ENTRY_ECONOMICS",
            failed_gate="REWARD_RISK_TOO_LOW", execution_attempted=False, position_opened=False,
        ),
    ]

    report = build_entry_funnel_report(records)

    assert report["capture_records"] == 3
    assert report["by_mode"]["SCALP"]["position_committed"] == 1
    assert report["by_mode"]["SCALP"]["pre_brain_blocked"] == 1
    assert report["by_mode"]["SWING"]["brain_blocked"] == 1
    assert report["by_final_status"]["POSITION_COMMITTED"] == 1
    assert report["by_failed_gate"]["REWARD_RISK_TOO_LOW"] == 1
    assert report["daily"]["2026-11-09"]["capture_records"] == 3
    assert report["approximate_symbol_mode_5m_windows"] == 3


def test_legacy_brain_record_without_final_decision_is_marked_unknown_not_failed():
    report = build_entry_funnel_report([_brain_record()])

    assert report["by_mode"]["SCALP"]["brain_allowed"] == 1
    assert report["by_mode"]["SCALP"]["final_outcome_unknown"] == 1
    assert report["by_mode"]["SCALP"]["position_committed"] == 0


def test_report_deduplicates_capture_identity():
    first = build_entry_funnel_record(
        _brain_record(), symbol="BTCUSDT", trade_mode="SCALP", capture_id="same",
        captured_at="2026-11-09T08:02:00+00:00", strategy_action="BUY",
        strategy_score=65, final_status="REJECTED_ENTRY_ECONOMICS",
        failed_gate="REWARD_RISK_TOO_LOW", execution_attempted=False, position_opened=False,
    )
    second = dict(first)
    second["final_decision"] = dict(first["final_decision"], status="POSITION_COMMITTED", position_opened=True)

    report = build_entry_funnel_report([first, second])

    assert report["capture_records"] == 1
    assert report["by_final_status"]["POSITION_COMMITTED"] == 1
