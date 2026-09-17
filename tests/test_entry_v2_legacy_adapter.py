from engine.entry_v2_adapter import EntryV2MarketFacts, build_entry_scenario, evaluate_legacy_with_entry_v2
from multi_candle_context import analyze_multi_candle_context


def candle(o, c, low=None, high=None, volume=100.0):
    low = o - 0.2 if low is None else low
    high = c + 0.2 if high is None else high
    return {"open": o, "close": c, "low": low, "high": high, "volume": volume}


def base_candles():
    return [
        candle(110, 109, 108.5, 110.2),
        candle(109, 108, 107.5, 109.2),
        candle(108, 107, 106.5, 108.2),
        candle(107, 106.7, 106.2, 107.2),
        candle(106.7, 106.3, 106.0, 106.9),
        candle(106.3, 106.55, 106.15, 106.8, 130),
        candle(106.55, 106.9, 106.35, 107.1, 135),
        candle(106.9, 107.2, 106.7, 107.4, 140),
        candle(107.2, 107.3, 107.0, 107.5, 145),
    ]


def legacy_result(**overrides):
    result = {
        "trade_mode": "SCALP",
        "score": 82,
        "scalp_score": 82,
        "swing_score": 55,
        "scalp_signal": "BUY",
        "swing_signal": "HOLD",
        "scalp_confirmed_reversal": False,
        "scalp_recovery_confirmation": True,
        "scalp_reasons": ["15M_BOLLINGER_NEAR_SUPPORT", "5M_RSI_RECOVERY_ZONE"],
        "volume_ratio_5m": 1.30,
    }
    result.update(overrides)
    return result


def facts(legacy):
    candles = base_candles()
    return EntryV2MarketFacts(
        legacy_result=legacy,
        candles_5m=candles,
        candles_15m=list(candles),
        candles_1h=list(candles),
        candles_4h=list(candles),
        stop_distance_percent=1.0,
        reward_risk=1.8,
        spread_percent=0.02,
    )


def test_recovery_does_not_become_structural_reversal():
    scenario = build_entry_scenario(facts(legacy_result()))
    structure = scenario["structure"]
    assert structure["higher_low"] is False
    assert structure["reclaim"] is False
    assert scenario["trigger"]["confirmed_reversal"] is False


def test_legacy_score_cannot_authorize_fake_recovery():
    decision = evaluate_legacy_with_entry_v2(facts(legacy_result()))
    assert decision.approved is False
    assert decision.decision in {"REJECT_NO_RECLAIM", "REJECT_COUNTERTREND"}


def test_multi_candle_structure_is_carried_into_v2_contract_for_all_timeframes():
    legacy = legacy_result(
        scalp_confirmed_reversal=True,
        scalp_recovery_confirmation=False,
        scalp_reasons=["15M_BOLLINGER_NEAR_SUPPORT"],
    )
    scenario = build_entry_scenario(facts(legacy))
    by_tf = scenario["structure"]["multi_candle_by_timeframe"]
    assert set(by_tf) == {"5m", "15m", "1h", "4h"}
    assert all(by_tf[tf]["patterns"] for tf in by_tf)
    assert scenario["structure"]["higher_low"] is True
    assert scenario["structure"]["reclaim"] is True
    assert "multi_candle_context_by_timeframe" in scenario["metadata"]


def test_higher_timeframe_structure_is_kept_separate_from_5m_trigger():
    legacy = legacy_result(
        scalp_confirmed_reversal=True,
        scalp_recovery_confirmation=False,
        scalp_reasons=["15M_BOLLINGER_NEAR_SUPPORT"],
    )
    scenario = build_entry_scenario(facts(legacy))
    assert scenario["market"]["1h_bias"] in {"BULLISH", "BEARISH", "NEUTRAL", "UNKNOWN"}
    assert scenario["market"]["4h_bias"] in {"BULLISH", "BEARISH", "NEUTRAL", "UNKNOWN"}
    assert scenario["trigger"]["confirmed_reversal"] is True


def test_four_candle_reversal_is_detected_explicitly():
    candles = [
        candle(100, 98, 97.5, 100.3),
        candle(98, 96, 95.5, 98.2),
        candle(96, 97, 95.6, 97.4),
        candle(97, 100, 96.8, 100.4),
        candle(100, 100.2),
        candle(100.2, 100.3),
        candle(100.3, 100.4),
        candle(100.4, 100.5),
    ]
    context = analyze_multi_candle_context(candles)
    assert "FOUR_C_BEAR_TO_BULL_REVERSAL" in context["patterns"]


def test_four_candle_bearish_sequence_can_raise_bearish_warning():
    candles = [
        candle(100, 101),
        candle(101, 100),
        candle(100, 99),
        candle(99, 98),
        candle(98, 97),
        candle(97, 96),
        candle(96, 95),
        candle(95, 94),
    ]
    context = analyze_multi_candle_context(candles)
    assert "FOUR_BEARISH_SEQUENCE" in context["patterns"]
    assert context["bearish_warning"] is True


def test_legacy_scalp_lane_never_falls_back_to_swing():
    legacy = legacy_result(scalp_signal="HOLD", swing_signal="BUY", trade_mode="SCALP")
    scenario = build_entry_scenario(facts(legacy))
    assert scenario["trade_mode"] == "SCALP"


def test_legacy_swing_lane_remains_swing():
    legacy = legacy_result(
        trade_mode="SWING",
        scalp_signal="BUY",
        swing_signal="BUY",
        score=84,
        scalp_score=70,
        swing_score=84,
    )
    scenario = build_entry_scenario(facts(legacy))
    assert scenario["trade_mode"] == "SWING"


def test_incomplete_higher_timeframe_data_is_exposed_not_fabricated():
    legacy = legacy_result()
    candles = base_candles()
    market_facts = EntryV2MarketFacts(
        legacy_result=legacy,
        candles_5m=candles,
        candles_15m=candles,
        candles_1h=[],
        candles_4h=[],
        stop_distance_percent=1.0,
        reward_risk=1.8,
        spread_percent=0.02,
    )
    scenario = build_entry_scenario(market_facts)
    assert scenario["structure"]["multi_candle_by_timeframe"]["1h"]["bias"] == "UNKNOWN"
    assert scenario["structure"]["multi_candle_by_timeframe"]["4h"]["bias"] == "UNKNOWN"
    assert scenario["metadata"]["mtf_context"]["available"] is True
