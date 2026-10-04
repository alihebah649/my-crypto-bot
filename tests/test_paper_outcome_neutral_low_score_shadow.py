from types import SimpleNamespace

from core.paper_outcome_evidence import build_paper_outcome_evidence


def test_paper_outcome_persists_neutral_low_score_shadow():
    position = SimpleNamespace(
        position_id="POS-test",
        symbol="LTCUSDT",
        trade_mode="SCALP",
        opened_at=100.0,
        closed_at=110.0,
        quantity=1.0,
        entry_price=69.13,
        current_price=69.62,
        highest_price=69.62,
        max_profit_percent=0.71,
        stop_loss=68.37,
        take_profit=None,
        gross_pnl=0.35,
        realized_pnl=0.25,
        total_fees=0.10,
        close_reason="TRAILING_STOP",
        entry_metadata={
            "trade_mode": "SCALP",
            "entry_stop_loss": 68.37,
        },
        exit_metadata={"exit_price": 69.62},
        entry_context={
            "strategy_score": {
                "trade_mode": "SCALP",
                "score": 69,
                "scalp_score": 69,
                "swing_score": 60,
                "mtf_bias": "NEUTRAL",
                "mtf_net": 0,
            }
        },
    )

    record = build_paper_outcome_evidence(position)
    experiment = record["entry_forensics"]["neutral_low_score_shadow"]

    assert experiment["rule_version"] == 1
    assert experiment["shadow_only"] is True
    assert experiment["gate_pass"] is False
    assert experiment["would_be_action"] == "WOULD_BLOCK"
    assert experiment["mtf_bias"] == "NEUTRAL"
    assert experiment["scalp_score"] == 69.0
