from engine.entry_engine import EntryEngineV2


BASE_SCENARIO = {
    "trade_mode": "SCALP",
    "setup_type": "REVERSAL",
    "market": {"5m_bias": "BULLISH", "15m_bias": "BULLISH", "1h_bias": "BULLISH", "4h_bias": "NEUTRAL", "btc_guard": "PASS"},
    "structure": {
        "location_at_support": True,
        "location_pullback": False,
        "selling_pressure_weakening": True,
        "higher_low": True,
        "reclaim": True,
        "continuation_break": False,
        "pullback_holds": False,
        "new_structure_after_prior_stop": True,
    },
    "trigger": {"confirmed_reversal": True, "volume_ratio_5m": 1.2, "overextended": False},
    "execution": {"closed_candle": True, "spread_percent": 0.02},
    "risk": {"stop_distance_percent": 1.0, "reward_risk": None, "target_status": "NO_TARGET_ABOVE_ENTRY"},
    "metadata": {"legacy_score": 90},
}


def test_no_target_above_entry_has_distinct_gate_reason():
    result = EntryEngineV2().evaluate(BASE_SCENARIO)
    assert result.decision == "REJECT_NO_VALID_TARGET"
    assert result.failed_gate == "NO_TARGET_ABOVE_ENTRY"


def test_no_target_meets_rr_has_distinct_gate_reason():
    scenario = {**BASE_SCENARIO, "risk": {**BASE_SCENARIO["risk"], "target_status": "NO_TARGET_MEETS_RR"}}
    result = EntryEngineV2().evaluate(scenario)
    assert result.decision == "REJECT_NO_VALID_TARGET"
    assert result.failed_gate == "NO_TARGET_MEETS_RR"


def test_missing_target_status_remains_data_pending():
    scenario = {**BASE_SCENARIO, "risk": {"stop_distance_percent": 1.0, "reward_risk": None}}
    result = EntryEngineV2().evaluate(scenario)
    assert result.decision == "REJECT_DATA_UNAVAILABLE"
    assert result.failed_gate == "REWARD_RISK_PENDING"
