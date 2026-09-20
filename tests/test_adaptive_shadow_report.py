from engine.entry_v2_shadow_report import build_entry_v2_shadow_report


def _scalp_capture(capture_id: str, approved: bool, *, strong_bear: bool = False):
    if strong_bear:
        bias = {"5m": "BULLISH", "15m": "BEARISH", "1h": "NEUTRAL", "4h": "BEARISH"}
        mtf_net, bear, bull = -34, 34, 0
    else:
        bias = {"5m": "BULLISH", "15m": "NEUTRAL", "1h": "BULLISH", "4h": "NEUTRAL"}
        mtf_net, bear, bull = 10, 5, 15
    return {
        "capture_id": capture_id,
        "captured_at": "2026-09-20T01:00:00Z",
        "symbol": "TESTUSDT",
        "legacy_result": {
            "trade_mode": "SCALP",
            "signal": "BUY",
            "scalp_signal": "BUY",
            "scalp_score": 75,
            "mtf_bias": "BEARISH" if strong_bear else "BULLISH",
            "mtf_net": mtf_net,
            "mtf_weighted_bear": bear,
            "mtf_weighted_bull": bull,
            "mtf_timeframe_bias": bias,
            "scalp_recovery_confirmation": True,
            "scalp_confirmed_reversal": True,
            "scalp_recovery_trigger_count": 3,
            "scalp_recovery_trigger_reasons": [
                "5M_RSI_RISING", "5M_PRICE_RECOVERY", "5M_BULLISH_BODY"
            ],
            "volume_ratio_5m": 1.2,
            "pattern_confirmed": True,
        },
        "entry_scenario": {
            "trade_mode": "SCALP",
            "risk": {
                "target_price": 101.0,
                "target_status": "VALID",
                "reward_risk": 1.2,
            }
        },
        "v2_decision": {
            "approved": approved,
            "decision": "APPROVED_SCALP" if approved else "REJECT_NO_RECLAIM",
            "trade_mode": "SCALP",
            "setup_type": "REVERSAL",
            "failed_gate": None if approved else "STRUCTURAL_RECLAIM_NOT_CONFIRMED",
        },
    }


def test_report_lists_approved_executions_and_adaptive_outcomes():
    captures = [
        _scalp_capture("CAP-A", True),
        _scalp_capture("CAP-B", False, strong_bear=True),
    ]
    positions = [
        {
            "position_id": "POS-A",
            "symbol": "TESTUSDT",
            "status": "CLOSED",
            "entry_metadata": {
                "entry_v2_shadow_capture_id": "CAP-A",
                "trade_mode": "SCALP",
            },
            "realized_pnl": -0.4,
            "total_fees": 0.1,
        },
        {
            "position_id": "POS-B",
            "symbol": "TESTUSDT",
            "status": "CLOSED",
            "entry_metadata": {
                "entry_v2_shadow_capture_id": "CAP-B",
                "trade_mode": "SCALP",
            },
            "realized_pnl": 0.2,
            "total_fees": 0.1,
        },
    ]

    report = build_entry_v2_shadow_report(captures, positions)

    assert [row["position_id"] for row in report["v2_approved_executions"]] == ["POS-A"]
    adaptive = report["adaptive_scalp_shadow"]["by_classification"]
    assert adaptive["NORMAL_SCALP"]["losses"] == 1
    assert adaptive["BEAR_RECOVERY_STRONG"]["wins"] == 1


def test_report_recomputes_adaptive_shadow_for_legacy_captures_without_field():
    capture = _scalp_capture("CAP-X", False, strong_bear=True)
    captures = [capture]
    positions = [{
        "position_id": "POS-X",
        "symbol": "TESTUSDT",
        "status": "CLOSED",
        "entry_metadata": {"entry_v2_shadow_capture_id": "CAP-X", "trade_mode": "SCALP"},
        "realized_pnl": -0.3,
        "total_fees": 0.1,
    }]
    report = build_entry_v2_shadow_report(captures, positions)
    row = report["rejected_executions"][0]
    assert row["adaptive_scalp_shadow"]["classification"] == "BEAR_RECOVERY_STRONG"
