from __future__ import annotations

from engine.entry_v2_shadow_report import build_entry_v2_shadow_report


def _capture(capture_id, symbol, captured_at, approved, lane="SCALP", gate=None, target_status="VALID", reward_risk=1.2):
    return {
        "capture_id": capture_id,
        "captured_at": captured_at,
        "symbol": symbol,
        "entry_scenario": {"risk": {"target_price": 110.0, "target_status": target_status, "reward_risk": reward_risk}},
        "v2_decision": {
            "approved": approved,
            "decision": "APPROVE" if approved else "REJECT",
            "trade_mode": lane,
            "setup_type": "SCALP_REVERSAL",
            "failed_gate": gate,
        },
    }


def test_shadow_report_builds_empirical_flow_and_rejected_execution_rows():
    captures = [
        _capture("CAP-B", "BNBUSDT", "2026-09-17T05:02:00Z", False, gate="NO_TARGET_ABOVE_ENTRY", target_status="NO_TARGET_ABOVE_ENTRY", reward_risk=None),
        _capture("CAP-A", "ADAUSDT", "2026-09-17T05:01:00Z", True, lane="SCALP"),
        _capture("CAP-C", "ETHUSDT", "2026-09-17T05:03:00Z", False, lane="SWING", gate="SELLER_FAILURE"),
    ]
    positions = [
        {"position_id": "POS-B", "symbol": "BNBUSDT", "status": "CLOSED", "entry_metadata": {"entry_v2_shadow_capture_id": "CAP-B"}, "realized_pnl": -2.0, "total_fees": 0.2},
        {"position_id": "POS-A", "symbol": "ADAUSDT", "status": "CLOSED", "entry_metadata": {"entry_v2_shadow_capture_id": "CAP-A"}, "realized_pnl": 1.5, "total_fees": 0.2},
        {"position_id": "POS-X", "symbol": "XRPUSDT", "status": "CLOSED", "entry_metadata": {}, "realized_pnl": -0.4, "total_fees": 0.1},
    ]

    report = build_entry_v2_shadow_report(captures, positions)

    assert report["coverage"] == {
        "captures": 3,
        "matched_positions": 2,
        "unmatched_positions": 1,
        "unmatched_captures": 1,
    }
    assert report["decision_flow"] == {
        "v2_approved": 1,
        "v2_rejected": 2,
        "legacy_executed_v2_rejected": 1,
    }

    rejected = report["legacy_executed_v2_rejected_outcomes"]
    assert rejected["positions"] == 1
    assert rejected["closed_positions"] == 1
    assert rejected["open_positions"] == 0
    assert rejected["losses"] == 1
    assert rejected["wins"] == 0
    assert rejected["realized_pnl"] == -2.0
    assert rejected["fees"] == 0.2

    rows = report["rejected_executions"]
    assert [row["position_id"] for row in rows] == ["POS-B"]
    assert rows[0]["symbol"] == "BNBUSDT"
    assert rows[0]["failed_gate"] == "NO_TARGET_ABOVE_ENTRY"
    assert rows[0]["target_status"] == "NO_TARGET_ABOVE_ENTRY"
    assert rows[0]["realized_pnl"] == -2.0
    assert rows[0]["fees"] == 0.2

    assert report["unmatched_capture_ids"] == ["CAP-C"]
    assert report["unmatched_position_ids"] == ["POS-X"]


def test_shadow_report_accepts_generators_and_caps_rejected_execution_rows():
    captures = iter([_capture(f"CAP-{i}", "SOLUSDT", f"2026-09-17T05:{i:02d}:00Z", False, gate="GATE") for i in range(3)])
    positions = iter([
        {"position_id": f"POS-{i}", "status": "OPEN", "entry_metadata": {"entry_v2_shadow_capture_id": f"CAP-{i}"}, "realized_pnl": 0.0, "total_fees": 0.1}
        for i in range(3)
    ])

    report = build_entry_v2_shadow_report(captures, positions, max_rejected_execution_rows=2)

    assert report["decision_flow"]["legacy_executed_v2_rejected"] == 3
    assert report["legacy_executed_v2_rejected_outcomes"]["open_positions"] == 3
    assert len(report["rejected_executions"]) == 2
    assert [row["position_id"] for row in report["rejected_executions"]] == ["POS-0", "POS-1"]



def test_shadow_report_exposes_maturity_experiment_outcomes():
    captures = [
        dict(_capture("CAP-MATURE", "ADAUSDT", "2026-09-21T05:01:00Z", False, gate="STRUCTURAL_RECLAIM_NOT_CONFIRMED"), adaptive_scalp_shadow={
            "classification": "NORMAL_SCALP",
            "maturity_experiment": {
                "rule_version": 1,
                "shadow_only": True,
                "gate_pass": True,
                "would_be_action": "WOULD_ALLOW",
                "reasons": ["RECOVERY_TRIGGER_COUNT_3_PLUS"],
            },
        }),
        dict(_capture("CAP-IMMATURE", "SOLUSDT", "2026-09-21T05:02:00Z", False, gate="STRUCTURAL_RECLAIM_NOT_CONFIRMED"), adaptive_scalp_shadow={
            "classification": "NORMAL_SCALP",
            "maturity_experiment": {
                "rule_version": 1,
                "shadow_only": True,
                "gate_pass": False,
                "would_be_action": "WOULD_BLOCK",
                "reasons": ["RECOVERY_TRIGGER_COUNT_BELOW_3"],
            },
        }),
    ]
    positions = [
        {
            "position_id": "POS-MATURE",
            "symbol": "ADAUSDT",
            "status": "CLOSED",
            "entry_metadata": {"entry_v2_shadow_capture_id": "CAP-MATURE", "trade_mode": "SCALP"},
            "realized_pnl": 1.25,
            "total_fees": 0.1,
        },
        {
            "position_id": "POS-IMMATURE",
            "symbol": "SOLUSDT",
            "status": "CLOSED",
            "entry_metadata": {"entry_v2_shadow_capture_id": "CAP-IMMATURE", "trade_mode": "SCALP"},
            "realized_pnl": -0.75,
            "total_fees": 0.1,
        },
    ]

    report = build_entry_v2_shadow_report(captures, positions)
    maturity = report["adaptive_scalp_shadow"]["maturity_experiment"]

    assert maturity["rule_version"] == 1
    assert maturity["shadow_only"] is True
    assert maturity["by_action"]["WOULD_ALLOW"] == {
        "positions": 1,
        "wins": 1,
        "losses": 0,
        "flat": 0,
        "realized_pnl": 1.25,
        "fees": 0.1,
    }
    assert maturity["by_action"]["WOULD_BLOCK"] == {
        "positions": 1,
        "wins": 0,
        "losses": 1,
        "flat": 0,
        "realized_pnl": -0.75,
        "fees": 0.1,
    }
