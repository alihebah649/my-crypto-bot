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
        "scalp_structural_confirmation": True,
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


def test_brain_blocks_scalp_without_structural_confirmation():
    brain = GuardedBrainAuthority()
    strategy = {
        "signal": "BUY",
        "scalp_signal": "BUY",
        "scalp_score": 90,
        "trade_mode": "SCALP",
        "scalp_confirmed_reversal": True,
        "scalp_recovery_confirmation": True,
        "scalp_structural_confirmation": False,
        "volume_ratio_5m": 2.0,
        "seller_failure_confirmed": True,
    }
    record = brain.evaluate_entry(
        "TESTUSDT", strategy, trade_mode="SCALP", market_regime="BULL"
    )
    assert record.allowed is False
    assert record.brain_reason == "SCALP_STRUCTURAL_CONFIRMATION_REQUIRED"


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
        "scalp_structural_confirmation": True,
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
        "scalp_structural_confirmation": True,
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
        "scalp_structural_confirmation": True,
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



def test_brain_promotes_selective_v2_veto_from_persisted_v2_failed_gate():
    brain = GuardedBrainAuthority()
    strategy = {
        "signal": "BUY",
        "scalp_signal": "BUY",
        "scalp_score": 77,
        "trade_mode": "SCALP",
        "scalp_confirmed_reversal": True,
        "scalp_recovery_confirmation": True,
        "scalp_structural_confirmation": True,
        "volume_ratio_5m": 1.91,
        "rsi5m": 51.2,
    }
    record = brain.evaluate_entry(
        "SUIUSDT",
        strategy,
        trade_mode="SCALP",
        market_regime="BEAR",
        entry_v2_shadow={
            "approved": False,
            "v2_failed_gate": "STRUCTURAL_RECLAIM_NOT_CONFIRMED",
            "trade_mode": "SCALP",
            "adaptive_scalp_shadow": {
                "regime": "BEAR",
                "classification": "BEAR_RECOVERY_CAUTION",
                "recovery_trigger_count": 3,
                "five_m_bias": "NEUTRAL",
                "volume_ratio_5m": 1.91,
            },
            "candle_patterns_5m": [
                "8C_SELL_OFF_TO_RECOVERY",
                "7C_LOWER_HIGH_STRUCTURE",
            ],
            "candle_patterns_15m": [
                "FOUR_BEARISH_SEQUENCE",
                "7C_LOWER_HIGH_STRUCTURE",
            ],
        },
    )

    assert record.allowed is False
    assert record.brain_action == "HOLD"
    assert record.brain_reason == "V2_STRUCTURAL_RECLAIM_RSI_PRESSURE"
    assert record.context["selective_v2_veto"] == "V2_STRUCTURAL_RECLAIM_RSI_PRESSURE"


def test_selective_v2_reads_prefixed_failed_gate_for_low_rsi_bear_recovery():
    brain = GuardedBrainAuthority()
    strategy = {
        "signal": "BUY",
        "scalp_signal": "BUY",
        "scalp_score": 65,
        "trade_mode": "SCALP",
        "scalp_confirmed_reversal": False,
        "scalp_recovery_confirmation": True,
        "scalp_structural_confirmation": True,
        "volume_ratio_5m": 1.29,
        "rsi5m": 39.1,
    }
    record = brain.evaluate_entry(
        "ARBUSDT",
        strategy,
        trade_mode="SCALP",
        market_regime="BULL",
        entry_v2_shadow={
            "approved": False,
            "v2_failed_gate": "STRUCTURAL_RECLAIM_NOT_CONFIRMED",
            "trade_mode": "SCALP",
            "adaptive_scalp_shadow": {
                "regime": "BEAR",
                "classification": "BEAR_WEAK_RECOVERY",
                "recovery_trigger_count": 3,
                "five_m_bias": "NEUTRAL",
                "volume_ratio_5m": 1.29,
            },
            "candle_patterns_5m": [
                "FOUR_C_BEAR_TO_BULL_REVERSAL",
                "7C_LOWER_HIGH_STRUCTURE",
            ],
            "candle_patterns_15m": [
                "FOUR_BEARISH_SEQUENCE",
                "7C_LOWER_HIGH_STRUCTURE",
            ],
        },
    )

    # This profile is intentionally not vetoed by the narrower hard class.
    assert record.allowed is True
    assert record.brain_action == "BUY"



def _countertrend_strategy(**overrides):
    strategy = {
        "signal": "BUY",
        "scalp_signal": "BUY",
        "scalp_score": 75,
        "score": 75,
        "trade_mode": "SCALP",
        "scalp_confirmed_reversal": True,
        "scalp_recovery_confirmation": True,
        "scalp_structural_confirmation": True,
        "rsi5m": 44.0,
        "mtf_net": -25,
        "mtf_bias": "BEARISH",
    }
    strategy.update(overrides)
    return strategy


def _v2_shadow(failed_gate, *, stop=0.8, classification="BEAR_RECOVERY", five_bias="NEUTRAL", five=None, fifteen=None):
    return {
        "approved": False,
        "v2_failed_gate": failed_gate,
        "trade_mode": "SCALP",
        "stop_distance_percent": stop,
        "adaptive_scalp_shadow": {
            "regime": "BEAR",
            "classification": classification,
            "recovery_trigger_count": 3,
            "five_m_bias": five_bias,
            "volume_ratio_5m": 1.2,
        },
        "candle_patterns_5m": five or [],
        "candle_patterns_15m": fifteen or [],
    }


def test_brain_blocks_deep_bear_tight_stop_without_higher_low():
    brain = GuardedBrainAuthority()
    record = brain.evaluate_entry(
        "SUIUSDT",
        _countertrend_strategy(),
        trade_mode="SCALP",
        market_regime="BEAR",
        entry_v2_shadow=_v2_shadow(
            "STRUCTURAL_RECLAIM_NOT_CONFIRMED",
            stop=0.94,
            five=["7C_LOWER_HIGH_STRUCTURE"],
            fifteen=["7C_LOWER_HIGH_STRUCTURE"],
        ),
    )
    assert record.allowed is False
    assert record.brain_reason == "BEAR_DEEP_COUNTERTREND_TIGHT_STOP"


def test_brain_preserves_wider_stop_countertrend_exception():
    brain = GuardedBrainAuthority()
    record = brain.evaluate_entry(
        "AVAXUSDT",
        _countertrend_strategy(mtf_net=-32, rsi5m=39.3),
        trade_mode="SCALP",
        market_regime="BEAR",
        entry_v2_shadow=_v2_shadow(
            "STRUCTURAL_RECLAIM_NOT_CONFIRMED",
            stop=1.53,
            classification="BEAR_RECOVERY_STRONG",
            five=["7C_LOWER_HIGH_STRUCTURE"],
            fifteen=["7C_LOWER_HIGH_STRUCTURE"],
        ),
    )
    # This test protects the absence of the *new* selective veto; the
    # existing Brain counter-trend policy may still reject the same profile.
    assert record.context["selective_v2_veto"] is None
    assert record.brain_reason != "BEAR_DEEP_COUNTERTREND_TIGHT_STOP"


def test_brain_blocks_bear_no_target_with_tight_stop():
    brain = GuardedBrainAuthority()
    record = brain.evaluate_entry(
        "ALGOUSDT",
        _countertrend_strategy(mtf_net=-11, mtf_bias="BEARISH", rsi5m=51.1),
        trade_mode="SCALP",
        market_regime="BEAR",
        entry_v2_shadow=_v2_shadow("NO_TARGET_MEETS_RR", stop=0.89),
    )
    assert record.allowed is False
    assert record.brain_reason == "BEAR_NO_TARGET_TIGHT_STOP"


def test_brain_blocks_weak_bear_no_reclaim_profile():
    brain = GuardedBrainAuthority()
    record = brain.evaluate_entry(
        "SOLUSDT",
        _countertrend_strategy(mtf_net=-8, mtf_bias="BEARISH", scalp_score=87, score=87, rsi5m=42.7),
        trade_mode="SCALP",
        market_regime="BEAR",
        entry_v2_shadow=_v2_shadow(
            "STRUCTURAL_RECLAIM_NOT_CONFIRMED",
            stop=0.73,
            five=["7C_LOWER_HIGH_STRUCTURE"],
            fifteen=["7C_LOWER_HIGH_STRUCTURE"],
        ),
    )
    assert record.allowed is False
    assert record.brain_reason == "BEAR_RECLAIM_WEAK_COUNTERTREND"


def test_brain_blocks_high_score_bear_seller_pressure_profile():
    brain = GuardedBrainAuthority()
    record = brain.evaluate_entry(
        "ARBUSDT",
        _countertrend_strategy(mtf_net=0, mtf_bias="NEUTRAL", scalp_score=81, score=81, rsi5m=42.7),
        trade_mode="SCALP",
        market_regime="BEAR",
        entry_v2_shadow=_v2_shadow(
            "SELLER_PRESSURE_NOT_INVALIDATED",
            stop=1.26,
            classification="BEAR_RECOVERY",
            five_bias="BEARISH",
            five=["7C_LOWER_HIGH_STRUCTURE"],
            fifteen=[],
        ),
    )
    assert record.allowed is False
    assert record.brain_reason == "BEAR_HIGH_SCORE_NO_SELLER_FAILURE"


def test_brain_promotes_low_rsi_swing_higher_timeframe_bearish_veto():
    brain = GuardedBrainAuthority()
    strategy = {
        "signal": "BUY",
        "swing_signal": "BUY",
        "swing_score": 80,
        "trade_mode": "SWING",
        "rsi5m": 26.03,
        "volume_ratio_5m": 1.2,
        "mtf_higher_timeframes_bearish": True,
    }
    record = brain.evaluate_entry(
        "SOLUSDT",
        strategy,
        trade_mode="SWING",
        market_regime="BEAR",
        entry_v2_shadow={
            "approved": False,
            "failed_gate": "SWING_HIGHER_TIMEFRAMES_BEARISH",
            "trade_mode": "SWING",
        },
    )

    assert record.allowed is False
    assert record.brain_action == "HOLD"
    assert record.brain_reason == "V2_SWING_HIGHER_TIMEFRAMES_BEARISH"
    assert record.context["selective_v2_veto"] == "V2_SWING_HIGHER_TIMEFRAMES_BEARISH"
