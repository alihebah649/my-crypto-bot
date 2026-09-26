from types import SimpleNamespace

from core.paper_outcome_evidence import build_paper_outcome_evidence


def test_build_paper_outcome_evidence_joins_entry_v2_and_brain():
    position = SimpleNamespace(
        position_id="POS-1",
        symbol="BNBUSDT",
        opened_at=100.0,
        closed_at=160.0,
        quantity=0.5,
        entry_price=700.0,
        current_price=708.0,
        stop_loss=693.0,
        take_profit=None,
        gross_pnl=4.0,
        realized_pnl=3.5,
        total_fees=0.5,
        close_reason=SimpleNamespace(name="TAKE_PROFIT"),
        entry_metadata={
            "trade_mode": "SCALP",
            "entry_stop_loss": 693.0,
            "entry_v2_shadow_capture_id": "cap-1",
            "entry_v2_shadow_decision": {
                "decision": "REJECT_NO_RECLAIM",
                "approved": False,
                "trade_mode": "SCALP",
                "setup_type": "REVERSAL",
                "failed_gate": "STRUCTURAL_RECLAIM_NOT_CONFIRMED",
                "reasons": ["NO_RECLAIM"],
            },
            "entry_v2_shadow_target_price": 715.0,
            "entry_v2_shadow_target_status": "VALID",
            "entry_v2_shadow_reward_risk": 1.5,
        },
        entry_context={
            "strategy_snapshot_source": "CANDIDATE_CAPTURE",
            "strategy_snapshot_captured_at": 1234.5,
            "strategy_score": {
                "score": 87,
                "scalp_score": 87,
                "swing_score": 80,
                "signal": "BUY",
                "scalp_signal": "BUY",
                "swing_signal": "BUY",
                "scalp_gate": True,
                "scalp_gate_reasons": ["CONFIRMED_5M_REVERSAL"],
                "scalp_confirmed_reversal": True,
                "scalp_recovery_confirmation": True,
                "scalp_high_confidence_recovery": True,
                "pattern": "BULLISH_BREAKOUT",
                "pattern_confirmed": True,
                "rsi5m": 39.8,
                "volume_ratio_5m": 1.9,
                "ema100": 704.0,
                "atr": 3.5,
                "lower_band": 695.0,
                "middle_band": 700.0,
                "upper_band": 705.0,
                "market_regime": "BULL",
                "symbol_regime": "BULL",
                "mtf_bias": "BULLISH",
                "mtf_net": 12,
                "seller_failure_confirmed": True,
                "entry_freshness_5m": {"state": "FRESH"},
            }
        },
        exit_metadata={"exit_price": 708.0},
    )

    brain = {
        "capture_id": "cap-1",
        "brain_action": "BUY",
        "brain_confidence": 87.0,
        "brain_reason": "CONFIRMED_ENTRY",
        "agreement": True,
    }

    record = build_paper_outcome_evidence(position, brain_record=brain)

    assert record["position_id"] == "POS-1"
    assert record["trade_mode"] == "SCALP"
    assert record["holding_seconds"] == 60.0
    assert record["realized_pnl"] == 3.5
    assert record["entry_v2"]["capture_id"] == "cap-1"
    assert record["entry_v2"]["approved"] is False
    assert record["entry_v2"]["failed_gate"] == "STRUCTURAL_RECLAIM_NOT_CONFIRMED"
    assert record["brain"]["capture_id"] == "cap-1"
    assert record["brain"]["action"] == "BUY"
    assert record["strategy"]["scalp_score"] == 87
    assert record["strategy"]["ema100"] == 704.0
    assert record["entry_forensics"]["entry_vs_ema100_percent"] < 0
    assert record["entry_forensics"]["atr_percent_of_entry"] == 0.5
    assert record["entry_forensics"]["strategy_snapshot_source"] == "CANDIDATE_CAPTURE"
    assert record["entry_forensics"]["strategy_snapshot_captured_at"] == 1234.5
    assert record["regime"]["market"] == "BULL"
    assert record["freshness_5m"]["state"] == "FRESH"


def test_paper_outcome_contains_scalp_forensics():
    position = SimpleNamespace(
        position_id="POS-FORENSIC",
        symbol="TESTUSDT",
        opened_at=100.0,
        closed_at=130.0,
        quantity=1.0,
        entry_price=100.0,
        current_price=98.5,
        stop_loss=98.5,
        take_profit=None,
        gross_pnl=-0.9,
        realized_pnl=-1.0,
        total_fees=0.1,
        close_reason=SimpleNamespace(name="STOP_LOSS"),
        entry_metadata={"trade_mode": "SCALP"},
        exit_metadata={"exit_price": 98.5},
        entry_context={
            "strategy_score": {
                "rsi5m": 49.0,
                "pattern": "BULLISH_BREAKOUT",
                "scalp_recovery_confirmation": True,
                "scalp_recovery_trigger_count": 3,
                "scalp_recovery_trigger_reasons": [
                    "5M_RSI_RISING", "5M_PRICE_RECOVERY", "5M_BULLISH_BODY"
                ],
                "volume_ratio_5m": 1.5,
                "mtf_bias": "BEARISH",
                "mtf_net": -10,
                "entry_freshness_5m": {
                    "state": "RECENT",
                    "decision_candle_age_seconds": 150.0,
                },
            }
        },
    )

    record = build_paper_outcome_evidence(position)
    assert record["entry_forensics"]["scalp_rsi_phase"] == "LATE_RECOVERY"
    assert record["entry_forensics"]["pattern_family"] == "BREAKOUT"
    assert record["entry_forensics"]["combined_signature"] == "LATE_RECOVERY__BREAKOUT"
    assert record["entry_forensics"]["recovery_trigger_count"] == 3
    assert record["entry_forensics"]["stop_distance_percent"] == 1.5


def test_paper_outcome_uses_frozen_entry_stop_after_protection_moves_stop():
    position = SimpleNamespace(
        position_id="POS-STOP-FROZEN",
        symbol="LTCUSDT",
        opened_at=100.0,
        closed_at=150.0,
        quantity=1.0,
        entry_price=66.04,
        current_price=67.9,
        stop_loss=66.1722122122,
        take_profit=None,
        gross_pnl=1.8,
        realized_pnl=1.7,
        total_fees=0.1,
        close_reason=SimpleNamespace(name="TRAILING_STOP"),
        entry_metadata={
            "trade_mode": "SCALP",
            "entry_stop_loss": 64.44336984,
        },
        entry_context={"strategy_score": {}},
        exit_metadata={"exit_price": 67.9},
    )

    record = build_paper_outcome_evidence(position)

    assert record["entry_stop_loss"] == 64.44336984
    assert record["stop_loss"] == 66.1722122122
    assert record["entry_forensics"]["stop_distance_percent"] == 2.417671
    assert record["entry_forensics"]["stop_distance_source"] == "ENTRY_METADATA"



def test_paper_outcome_marks_current_stop_at_or_above_entry_as_invalid_forensics():
    position = SimpleNamespace(
        position_id="POS-INVALID-STOP",
        symbol="DOTUSDT",
        opened_at=100.0,
        closed_at=130.0,
        quantity=1.0,
        entry_price=1.196,
        current_price=1.21,
        stop_loss=1.1983943943943942,
        take_profit=None,
        gross_pnl=0.5,
        realized_pnl=0.45,
        total_fees=0.05,
        close_reason=SimpleNamespace(name="TRAILING_STOP"),
        entry_metadata={"trade_mode": "SCALP"},
        exit_metadata={"exit_price": 1.21},
        entry_context={"strategy_score": {}},
    )

    record = build_paper_outcome_evidence(position)

    assert record["entry_forensics"]["stop_distance_percent"] == 0.0
    assert record["entry_forensics"]["stop_distance_valid"] is False
    assert record["entry_forensics"]["stop_distance_invalid_reason"] == "STOP_AT_OR_ABOVE_ENTRY"
    assert record["entry_forensics"]["stop_distance_source"] == "POSITION_CURRENT_STOP_FALLBACK"
