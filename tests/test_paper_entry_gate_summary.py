from core.paper_entry_gate_summary import build_paper_entry_gate_summary


def test_entry_summary_explains_scalp_score_rejected_by_gate():
    payload = build_paper_entry_gate_summary(
        {
            "ALGOUSDT": {
                "score": 65,
                "trade_mode": "NONE",
                "scalp_score": 65,
                "swing_score": 61,
                "scalp_signal": "HOLD",
                "swing_signal": "HOLD",
                "scalp_gate": False,
                "scalp_gate_reasons": [
                    "5M_VOLUME_TOO_LOW",
                    "SCALP_STRUCTURE_NOT_CONFIRMED",
                ],
                "scalp_recovery_confirmation": False,
                "scalp_structural_confirmation": False,
            }
        },
        scalp_threshold=65,
        swing_threshold=80,
        venue_mode="MIXED",
    )

    row = payload["top_symbols"][0]
    assert payload["scalp_scores_at_or_above_threshold"] == 1
    assert payload["scalp_signals_buy"] == 0
    assert payload["scalp_gate_blocked_at_threshold"] == 1
    assert row["scalp_status"] == "GATE_BLOCKED"
    assert row["scalp_gate_reasons"] == [
        "5M_VOLUME_TOO_LOW",
        "SCALP_STRUCTURE_NOT_CONFIRMED",
    ]
    assert payload["paper_only"] is True


def test_entry_summary_identifies_threshold_shortfall_without_claiming_gate_rejection():
    payload = build_paper_entry_gate_summary(
        {
            "RENDERUSDT": {
                "score": 64,
                "trade_mode": "NONE",
                "scalp_score": 64,
                "swing_score": 49,
                "scalp_signal": "HOLD",
                "swing_signal": "HOLD",
                "scalp_gate": False,
                "scalp_gate_reasons": ["5M_VOLUME_TOO_LOW"],
            }
        }
    )

    row = payload["top_symbols"][0]
    assert payload["scalp_scores_at_or_above_threshold"] == 0
    assert payload["swing_scores_at_or_above_threshold"] == 0
    assert payload["buy_symbol_count"] == 0
    assert row["scalp_status"] == "BELOW_THRESHOLD"
    assert row["swing_status"] == "BELOW_THRESHOLD"


def test_entry_summary_includes_compact_trace_only_for_current_buy_candidates():
    payload = build_paper_entry_gate_summary(
        {
            "BTCUSDT": {
                "score": 82,
                "trade_mode": "SWING",
                "scalp_score": 58,
                "swing_score": 82,
                "scalp_signal": "HOLD",
                "swing_signal": "BUY",
                "scalp_gate": False,
                "scalp_gate_reasons": ["5M_VOLUME_TOO_LOW"],
            },
            "ETHUSDT": {
                "score": 58,
                "trade_mode": "NONE",
                "scalp_score": 58,
                "swing_score": 51,
                "scalp_signal": "HOLD",
                "swing_signal": "HOLD",
                "scalp_gate": False,
                "scalp_gate_reasons": ["NO_15M_MACRO_SUPPORT"],
            },
        },
        entry_diagnostics={
            "BTCUSDT": {
                "result": "REJECTED_BRAIN_AUTHORITY",
                "execution": "NOT_RUN",
                "brain_authority_rejection_reason": "SELLER_PRESSURE_NOT_INVALIDATED",
                "brain_authority_by_mode": {
                    "SWING": {
                        "allowed": False,
                        "decision_state": "BLOCK",
                        "brain_reason": "SELLER_PRESSURE_NOT_INVALIDATED",
                    }
                },
                "pre_trade": {"btc_crash_guard": "PASS"},
            },
            "ETHUSDT": {"result": "REJECTED_EXISTING_POSITION"},
        },
    )

    rows = {row["symbol"]: row for row in payload["top_symbols"]}
    assert rows["BTCUSDT"]["entry_trace"]["result"] == "REJECTED_BRAIN_AUTHORITY"
    assert rows["BTCUSDT"]["entry_trace"]["brain_authority_by_mode"]["SWING"]["allowed"] is False
    assert "entry_trace" not in rows["ETHUSDT"]
