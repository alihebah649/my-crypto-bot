from core.brain_authority import GuardedBrainAuthority


def test_guarded_brain_allows_confirmed_bull_scalp_before_risk():
    brain = GuardedBrainAuthority()
    strategy = {
        "signal": "BUY",
        "scalp_signal": "BUY",
        "scalp_score": 70,
        "swing_score": 50,
        "trade_mode": "SCALP",
        "scalp_confirmed_reversal": True,
        "scalp_recovery_confirmation": False,
        "volume_ratio_5m": 1.20,
        "seller_failure_confirmed": True,
        "mtf_net": 8,
        "mtf_weighted_bull": 20,
        "mtf_weighted_bear": 12,
    }

    record = brain.evaluate_entry(
        "TESTUSDT",
        strategy,
        trade_mode="SCALP",
        market_regime="BULL",
    )

    assert record.allowed is True
    assert record.brain_action == "BUY"
    assert record.stage == "ENTRY_GATE"


def test_guarded_brain_blocks_strong_bear_scalp_without_seller_failure():
    brain = GuardedBrainAuthority()
    strategy = {
        "signal": "BUY",
        "scalp_signal": "BUY",
        "scalp_score": 83,
        "trade_mode": "SCALP",
        "scalp_confirmed_reversal": True,
        "volume_ratio_5m": 1.30,
        "seller_failure_confirmed": False,
        "mtf_higher_timeframes_bearish": True,
        "mtf_net": -30,
        "mtf_weighted_bull": 0,
        "mtf_weighted_bear": 30,
    }

    record = brain.evaluate_entry(
        "TESTUSDT",
        strategy,
        trade_mode="SCALP",
        market_regime="BEAR",
    )

    assert record.allowed is False
    assert record.brain_action == "HOLD"
    assert record.brain_reason == "BEAR_SELLER_FAILURE_NOT_CONFIRMED"


def test_guarded_brain_never_overrides_risk_lock():
    brain = GuardedBrainAuthority()
    strategy = {
        "signal": "BUY",
        "scalp_signal": "BUY",
        "scalp_score": 95,
        "trade_mode": "SCALP",
        "scalp_confirmed_reversal": True,
        "volume_ratio_5m": 2.0,
        "seller_failure_confirmed": True,
    }

    record = brain.evaluate_entry(
        "TESTUSDT",
        strategy,
        trade_mode="SCALP",
        market_regime="BULL",
        risk_locked=True,
    )

    assert record.allowed is False
    assert record.brain_action == "HOLD"
    assert record.brain_reason == "RISK_LOCKED"


def test_position_observation_keeps_safety_boundary():
    brain = GuardedBrainAuthority()
    record = brain.evaluate_position(
        "TESTUSDT",
        {"score": 80, "trade_mode": "SCALP"},
        pnl_percent=-0.8,
        hard_stop_triggered=True,
        market_regime="BEAR",
    )

    assert record.brain_action == "SELL"
    assert record.brain_reason == "HARD_STOP"
    assert record.allowed is False
    assert record.context["safety_boundary"] == "Risk/TradeManager remain authoritative"
