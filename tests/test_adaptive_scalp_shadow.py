from engine.adaptive_scalp_shadow import classify_adaptive_scalp


def _legacy(**overrides):
    base = {
        "trade_mode": "SCALP",
        "scalp_signal": "BUY",
        "scalp_score": 70,
        "signal": "BUY",
        "mtf_bias": "BULLISH",
        "mtf_net": 10,
        "mtf_weighted_bull": 15,
        "mtf_weighted_bear": 5,
        "mtf_timeframe_bias": {
            "5m": "BULLISH",
            "15m": "BULLISH",
            "1h": "BULLISH",
            "4h": "NEUTRAL",
        },
        "scalp_recovery_confirmation": True,
        "scalp_confirmed_reversal": True,
        "scalp_recovery_trigger_count": 3,
        "scalp_recovery_trigger_reasons": [
            "5M_RSI_RISING",
            "5M_PRICE_RECOVERY",
            "5M_BULLISH_BODY",
        ],
        "volume_ratio_5m": 1.2,
        "pattern_confirmed": True,
    }
    base.update(overrides)
    return base


def test_non_bear_scalp_is_normal():
    result = classify_adaptive_scalp(_legacy())
    assert result["classification"] == "NORMAL_SCALP"
    assert result["advisory_action"] == "PASSIVE_SHADOW"


def test_strong_bear_without_strong_recovery_is_high_risk():
    result = classify_adaptive_scalp(
        _legacy(
            mtf_bias="BEARISH",
            mtf_net=-40,
            mtf_weighted_bull=0,
            mtf_weighted_bear=40,
            mtf_timeframe_bias={
                "5m": "BEARISH",
                "15m": "BEARISH",
                "1h": "BEARISH",
                "4h": "BEARISH",
            },
            scalp_recovery_confirmation=False,
            scalp_confirmed_reversal=False,
            scalp_recovery_trigger_count=0,
            volume_ratio_5m=2.0,
            pattern_confirmed=False,
        )
    )
    assert result["regime"] == "BEAR"
    assert result["strong_bear"] is True
    assert result["classification"] == "BEAR_HIGH_RISK"
    assert result["advisory_action"] == "HOLD_SHADOW"


def test_strong_bear_recovery_gets_caution_when_volume_is_weak():
    result = classify_adaptive_scalp(
        _legacy(
            mtf_bias="BEARISH",
            mtf_net=-34,
            mtf_weighted_bull=0,
            mtf_weighted_bear=34,
            mtf_timeframe_bias={
                "5m": "NEUTRAL",
                "15m": "BEARISH",
                "1h": "NEUTRAL",
                "4h": "BEARISH",
            },
            volume_ratio_5m=0.85,
        )
    )
    assert result["classification"] == "BEAR_RECOVERY_CAUTION"
    assert result["advisory_action"] == "CAUTION_SHADOW"


def test_strong_bear_requires_5m_strength_for_strong_recovery():
    result = classify_adaptive_scalp(
        _legacy(
            mtf_bias="BEARISH",
            mtf_net=-34,
            mtf_weighted_bull=0,
            mtf_weighted_bear=34,
            mtf_timeframe_bias={
                "5m": "BULLISH",
                "15m": "BEARISH",
                "1h": "NEUTRAL",
                "4h": "BEARISH",
            },
            volume_ratio_5m=1.2,
        )
    )
    assert result["classification"] == "BEAR_RECOVERY_STRONG"
    assert result["advisory_action"] == "PASSIVE_SHADOW"


def test_swing_is_not_reclassified_as_scalp():
    result = classify_adaptive_scalp(_legacy(trade_mode="SWING"))
    assert result["classification"] == "NOT_APPLICABLE"


def test_timing_profile_distinguishes_deep_mid_and_late_recovery():
    from engine.adaptive_scalp_shadow import derive_scalp_timing_profile

    assert derive_scalp_timing_profile({"rsi5m": 28, "pattern": "BULLISH_ENGULFING"}) == {
        "rsi_phase": "EARLY_DEEP_RECOVERY",
        "pattern_family": "ENGULFING",
        "combined_signature": "EARLY_DEEP_RECOVERY__ENGULFING",
    }
    assert derive_scalp_timing_profile({"rsi5m": 40, "pattern": "BULLISH_ENGULFING"})["rsi_phase"] == "MID_RECOVERY"
    assert derive_scalp_timing_profile({"rsi5m": 49, "pattern": "BULLISH_BREAKOUT"}) == {
        "rsi_phase": "LATE_RECOVERY",
        "pattern_family": "BREAKOUT",
        "combined_signature": "LATE_RECOVERY__BREAKOUT",
    }


def test_timing_profile_is_descriptive_only():
    result = classify_adaptive_scalp(_legacy(rsi5m=49, pattern="BULLISH_BREAKOUT"))
    assert result["timing_profile"]["combined_signature"] == "LATE_RECOVERY__BREAKOUT"
    assert result["advisory_action"] in {"PASSIVE_SHADOW", "CAUTION_SHADOW", "HOLD_SHADOW"}



def test_maturity_experiment_passes_only_with_three_or_more_recovery_triggers():
    mature = classify_adaptive_scalp(_legacy(scalp_recovery_trigger_count=3))
    immature = classify_adaptive_scalp(_legacy(scalp_recovery_trigger_count=2))

    assert mature["maturity_experiment"] == {
        "rule_version": 1,
        "shadow_only": True,
        "gate_pass": True,
        "would_be_action": "WOULD_ALLOW",
        "reasons": ["RECOVERY_TRIGGER_COUNT_3_PLUS"],
    }
    assert immature["maturity_experiment"] == {
        "rule_version": 1,
        "shadow_only": True,
        "gate_pass": False,
        "would_be_action": "WOULD_BLOCK",
        "reasons": ["RECOVERY_TRIGGER_COUNT_BELOW_3"],
    }


def test_maturity_experiment_does_not_change_execution_facing_classification():
    result = classify_adaptive_scalp(_legacy(scalp_recovery_trigger_count=2))
    assert result["classification"] == "NORMAL_SCALP"
    assert result["advisory_action"] == "PASSIVE_SHADOW"
    assert result["maturity_experiment"]["shadow_only"] is True
