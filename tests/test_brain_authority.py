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


def test_brain_promotes_selective_entry_v2_structure_risk_veto():
    brain = GuardedBrainAuthority()
    strategy = {
        "signal": "BUY",
        "scalp_signal": "BUY",
        "scalp_score": 69,
        "trade_mode": "SCALP",
        "scalp_confirmed_reversal": False,
        "scalp_recovery_confirmation": True,
        "volume_ratio_5m": 0.84,
        "rsi5m": 49.5,
        "mtf_net": 8,
        "mtf_weighted_bull": 20,
        "mtf_weighted_bear": 12,
    }
    record = brain.evaluate_entry(
        "SOLUSDT",
        strategy,
        trade_mode="SCALP",
        market_regime="BULL",
        entry_v2_shadow={
            "approved": False,
            "failed_gate": "STRUCTURAL_RECLAIM_NOT_CONFIRMED",
            "trade_mode": "SCALP",
        },
    )
    assert record.allowed is False
    assert record.brain_action == "HOLD"
    assert record.brain_reason == "V2_STRUCTURAL_RECLAIM_RSI_PRESSURE"
    assert record.context["selective_v2_veto"] == "V2_STRUCTURAL_RECLAIM_RSI_PRESSURE"


def test_brain_does_not_promote_low_rsi_seller_pressure_failure():
    brain = GuardedBrainAuthority()
    strategy = {
        "signal": "BUY",
        "scalp_signal": "BUY",
        "scalp_score": 87,
        "trade_mode": "SCALP",
        "scalp_confirmed_reversal": True,
        "scalp_recovery_confirmation": True,
        "volume_ratio_5m": 2.0,
        "rsi5m": 42.8,
    }
    record = brain.evaluate_entry(
        "TESTUSDT",
        strategy,
        trade_mode="SCALP",
        market_regime="BULL",
        entry_v2_shadow={
            "approved": False,
            "failed_gate": "SELLER_PRESSURE_NOT_INVALIDATED",
            "trade_mode": "SCALP",
        },
    )
    assert record.allowed is True
    assert record.brain_action == "BUY"


def test_brain_promotes_selective_swing_structure_risk_veto():
    brain = GuardedBrainAuthority()
    strategy = {
        "signal": "BUY",
        "swing_signal": "BUY",
        "swing_score": 85,
        "trade_mode": "SWING",
        "rsi5m": 49.2,
        "mtf_net": 13,
    }
    record = brain.evaluate_entry(
        "SOLUSDT",
        strategy,
        trade_mode="SWING",
        market_regime="BULL",
        entry_v2_shadow={
            "approved": False,
            "failed_gate": "SWING_STRUCTURE_OR_HTF_ALIGNMENT_MISSING",
            "trade_mode": "SWING",
        },
    )
    assert record.allowed is False
    assert record.brain_reason == "V2_SWING_STRUCTURE_RSI_PRESSURE"
