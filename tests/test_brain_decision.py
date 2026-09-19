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


def test_bear_swing_entry_is_blocked_but_not_all_entries():
    d = BrainDecisionEngine().decide_entry(
        88,
        "BUY",
        True,
        market_regime="BEAR",
        trade_mode="SWING",
        swing_score=88,
    )
    assert d.action == "HOLD"
    assert d.reason == "BEAR_SWING_DISABLED"


def test_bear_scalp_requires_structural_reversal_quality():
    d = BrainDecisionEngine().decide_entry(
        70,
        "BUY",
        True,
        market_regime="BEAR",
        trade_mode="SCALP",
        scalp_score=70,
        volume_ratio_5m=0.82,
        seller_failure_confirmed=True,
    )
    assert d.action == "HOLD"
    assert d.reason == "BEAR_VOLUME_NOT_CONFIRMING"


def test_bear_scalp_can_buy_only_on_confirmed_countertrend_reversal():
    d = BrainDecisionEngine().decide_entry(
        70,
        "BUY",
        True,
        market_regime="BEAR",
        trade_mode="SCALP",
        scalp_score=70,
        scalp_recovery_confirmation=True,
        volume_ratio_5m=1.35,
        seller_failure_confirmed=True,
        higher_timeframe_bearish=False,
    )
    assert d.action == "BUY"
    assert d.reason == "BEAR_COUNTERTREND_SCALP_CONFIRMED"
    assert d.metadata["countertrend"] is True


def test_bear_exit_brain_can_protect_profit():
    d = BrainDecisionEngine().decide_position(
        1.2,
        market_regime="BEAR",
        age_minutes=20,
    )
    assert d.action == "SELL"
    assert d.reason == "BEAR_PROFIT_PROTECTION"


def test_bear_exit_brain_can_cut_weak_recovery():
    d = BrainDecisionEngine().decide_position(
        -1.8,
        market_regime="BEAR",
        recovery_active=True,
        recovery_score=35,
        age_minutes=20,
    )
    assert d.action == "SELL"
    assert d.reason == "BEAR_RECOVERY_WEAK"


def test_bear_market_can_keep_a_strong_local_bull_swing():
    d = BrainDecisionEngine().decide_entry(
        92,
        "BUY",
        True,
        market_regime="BEAR",
        symbol_regime="BULL",
        trade_mode="SWING",
        swing_score=92,
        higher_timeframe_bearish=False,
    )
    assert d.action == "BUY"


def test_swing_brain_rejects_unaligned_mtf_context_below_strong_threshold():
    d = BrainDecisionEngine().decide_entry(
        83,
        "BUY",
        trade_mode="SWING",
        swing_score=83,
        symbol_regime="BULL",
        market_regime="BULL",
        mtf_aligned_bullish=False,
        mtf_countertrend_veto=False,
    )
    assert d.action == "HOLD"
    assert d.reason == "SWING_MTF_ALIGNMENT_MISSING"


def test_swing_brain_rejects_explicit_countertrend_veto():
    d = BrainDecisionEngine().decide_entry(
        91,
        "BUY",
        trade_mode="SWING",
        swing_score=91,
        symbol_regime="BULL",
        market_regime="BULL",
        mtf_aligned_bullish=True,
        mtf_countertrend_veto=True,
    )
    assert d.action == "HOLD"
    assert d.reason == "MTF_COUNTERTREND_VETO"
