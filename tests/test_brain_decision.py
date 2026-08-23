from core.brain_decision import BrainDecisionEngine


def test_risk_lock_always_blocks_entry():
    d = BrainDecisionEngine().decide_entry(99, "BUY", True, risk_locked=True)
    assert d.action == "HOLD"
    assert d.reason == "RISK_LOCKED"


def test_entry_requires_confirmed_reversal():
    d = BrainDecisionEngine().decide_entry(92, "BUY", False)
    assert d.action == "HOLD"
    assert d.reason == "NO_CONFIRMED_REVERSAL"


def test_confirmed_high_score_can_buy():
    d = BrainDecisionEngine().decide_entry(92, "BUY", True)
    assert d.action == "BUY"


def test_hard_stop_is_authoritative():
    d = BrainDecisionEngine().decide_position(-3.0, hard_stop_triggered=True, recovery_active=True)
    assert d.action == "SELL"
    assert d.metadata["authoritative"] is True


def test_recovery_can_recommend_hold_without_overriding_exit_layer():
    d = BrainDecisionEngine().decide_position(-2.0, recovery_active=True, recovery_score=80)
    assert d.action == "HOLD"
    assert d.exception == "RECOVERY_HOLD"


def test_stale_losing_position_is_review_not_forced_sell():
    d = BrainDecisionEngine().decide_position(-0.5, age_minutes=300)
    assert d.action == "REVIEW"
    assert d.exception == "EXTENDED_HOLD_REVIEW"
