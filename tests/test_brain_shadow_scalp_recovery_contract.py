from core.brain_decision import BrainDecisionEngine


def test_brain_accepts_scalp_recovery_at_65_without_pattern():
    decision = BrainDecisionEngine().decide_entry(
        score=66,
        scalp_score=66,
        signal="BUY",
        trade_mode="SCALP",
        scalp_confirmed_reversal=False,
        scalp_recovery_confirmation=True,
    )
    assert decision.action == "BUY"
    assert decision.reason == "SCALP_RECOVERY_CONFIRMED"


def test_brain_rejects_scalp_context_without_recovery_or_pattern():
    decision = BrainDecisionEngine().decide_entry(
        score=66,
        scalp_score=66,
        signal="BUY",
        trade_mode="SCALP",
        scalp_confirmed_reversal=False,
        scalp_recovery_confirmation=False,
    )
    assert decision.action == "HOLD"
    assert decision.reason == "NO_CONFIRMED_REVERSAL_OR_RECOVERY"


def test_brain_keeps_swing_80_point_lane():
    decision = BrainDecisionEngine().decide_entry(
        score=80,
        swing_score=80,
        signal="BUY",
        trade_mode="SWING",
    )
    assert decision.action == "BUY"
