from __future__ import annotations

from engine.entry_v2_outcome_analysis import analyze_entry_v2_outcomes


def _capture(capture_id, approved, lane="SCALP", gate=None):
    return {
        "capture_id": capture_id,
        "v2_decision": {
            "approved": approved,
            "trade_mode": lane,
            "failed_gate": gate,
        },
    }


def test_outcome_analysis_joins_by_capture_id_and_separates_hypothetical_v2_rejections():
    captures = [
        _capture("CAP-A", True, "SCALP"),
        _capture("CAP-B", False, "SCALP", "NO_TARGET_ABOVE_ENTRY"),
        _capture("CAP-C", True, "SWING"),
    ]
    positions = [
        {"position_id": "POS-A", "status": "CLOSED", "entry_metadata": {"entry_v2_shadow_capture_id": "CAP-A", "trade_mode": "SCALP"}, "realized_pnl": 1.5, "total_fees": 0.2},
        {"position_id": "POS-B", "status": "CLOSED", "entry_metadata": {"entry_v2_shadow_capture_id": "CAP-B", "trade_mode": "SCALP"}, "realized_pnl": -2.0, "total_fees": 0.2},
        {"position_id": "POS-C", "status": "OPEN", "entry_metadata": {"entry_v2_shadow_capture_id": "CAP-C", "trade_mode": "SWING"}, "realized_pnl": 0.0, "total_fees": 0.1},
        {"position_id": "POS-D", "status": "CLOSED", "entry_metadata": {}, "realized_pnl": -0.5, "total_fees": 0.1},
    ]

    report = analyze_entry_v2_outcomes(captures, positions)

    assert report["capture_count"] == 3
    assert report["matched_position_count"] == 3
    assert report["unmatched_position_count"] == 1
    assert report["unmatched_position_ids"] == ["POS-D"]
    assert report["unmatched_capture_count"] == 0
    assert report["legacy_executed_v2_rejected"] == 1
    assert report["legacy_executed_v2_rejected_position_ids"] == ["POS-B"]

    approved = report["by_decision"]["V2_APPROVED"]
    assert approved["positions"] == 2
    assert approved["closed_positions"] == 1
    assert approved["wins"] == 1
    assert approved["realized_pnl"] == 1.5

    rejected = report["by_decision"]["V2_REJECTED"]
    assert rejected["positions"] == 1
    assert rejected["losses"] == 1
    assert rejected["realized_pnl"] == -2.0
    assert report["by_failed_gate"]["NO_TARGET_ABOVE_ENTRY"]["losses"] == 1


def test_outcome_analysis_handles_generator_inputs():
    captures = iter([_capture("CAP-A", True)])
    positions = iter([{"position_id": "POS-A", "status": "CLOSED", "entry_metadata": {"entry_v2_shadow_capture_id": "CAP-A"}, "realized_pnl": 0.5, "total_fees": 0.1}])

    report = analyze_entry_v2_outcomes(captures, positions)
    assert report["matched_position_count"] == 1
    assert report["by_decision"]["V2_APPROVED"]["wins"] == 1
