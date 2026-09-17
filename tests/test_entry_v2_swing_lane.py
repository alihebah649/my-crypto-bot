from types import SimpleNamespace

from engine.entry_engine import EntryEngineV2


ENGINE = EntryEngineV2()


def scenario(**overrides):
    base = dict(
        trade_mode="SWING",
        setup_type=None,
        market={"5m_bias": "BULLISH", "15m_bias": "BULLISH", "1h_bias": "BULLISH", "4h_bias": "BULLISH", "btc_guard": "PASS"},
        structure={"location_pullback": True, "pullback_holds": True, "higher_low": True, "reclaim": True, "continuation_break": True},
        trigger={"confirmed_reversal": True, "volume_ratio_5m": 1.05},
        execution={"closed_candle": True, "spread_percent": 0.03},
        risk={"stop_distance_percent": 2.0, "reward_risk": 1.8},
        metadata={"legacy_score": 81},
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_swing_lane_is_distinct_from_scalp_threshold():
    result = ENGINE.evaluate(scenario())
    assert result.approved is True
    assert result.decision == "APPROVED_SWING"
    assert result.trade_mode == "SWING"
    assert result.diagnostics["lane_threshold"] == 80
    assert result.diagnostics["legacy_score_used_as_gate"] is False


def test_swing_rejects_bearish_higher_timeframes():
    s = scenario(market={"5m_bias": "RECOVERY", "15m_bias": "BEARISH", "1h_bias": "BEARISH", "4h_bias": "BEARISH", "btc_guard": "PASS"})
    result = ENGINE.evaluate(s)
    assert result.decision == "REJECT_COUNTERTREND"


def test_swing_requires_higher_timeframe_alignment_and_structure():
    s = scenario(market={"5m_bias": "BULLISH", "15m_bias": "NEUTRAL", "1h_bias": "NEUTRAL", "4h_bias": "NEUTRAL", "btc_guard": "PASS"})
    result = ENGINE.evaluate(s)
    assert result.decision == "REJECT_NO_RECLAIM"


def test_swing_has_its_own_reward_floor():
    s = scenario(risk={"stop_distance_percent": 2.0, "reward_risk": 1.2})
    result = ENGINE.evaluate(s)
    assert result.decision == "REJECT_LOW_REWARD"


def test_swing_allows_wider_stop_than_scalp_but_keeps_a_hard_cap():
    valid = ENGINE.evaluate(scenario(risk={"stop_distance_percent": 4.0, "reward_risk": 2.0}))
    invalid = ENGINE.evaluate(scenario(risk={"stop_distance_percent": 5.5, "reward_risk": 2.0}))
    assert valid.decision == "APPROVED_SWING"
    assert invalid.decision == "REJECT_STOP_TOO_WIDE"


def test_swing_volume_floor_is_lower_than_scalp_but_still_required():
    valid = ENGINE.evaluate(scenario(trigger={"confirmed_reversal": True, "volume_ratio_5m": 0.95}))
    invalid = ENGINE.evaluate(scenario(trigger={"confirmed_reversal": True, "volume_ratio_5m": 0.85}))
    assert valid.decision == "APPROVED_SWING"
    assert invalid.decision == "REJECT_NO_VOLUME_CONFIRM"
