from engine.entry_v2_adapter import EntryV2MarketFacts
from engine.entry_v2_capture import capture_entry_v2, capture_summary, replay_captured


def candle(o, c, low=None, high=None, volume=100.0):
    low = o - 0.2 if low is None else low
    high = c + 0.2 if high is None else high
    return {"open": o, "close": c, "low": low, "high": high, "volume": volume}


def legacy_reversal():
    return {
        "signal": "BUY",
        "trade_mode": "SCALP",
        "score": 68,
        "scalp_score": 68,
        "swing_score": 52,
        "scalp_signal": "BUY",
        "swing_signal": "HOLD",
        "scalp_confirmed_reversal": True,
        "scalp_recovery_confirmation": False,
        "scalp_reasons": ["15M_BOLLINGER_NEAR_SUPPORT", "5M_BULLISH_ENGULFING_CONFIRMED"],
        "volume_ratio_5m": 1.30,
    }


def facts():
    c = [
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
    return EntryV2MarketFacts(
        legacy_result=legacy_reversal(),
        candles_5m=c,
        candles_15m=list(c),
        candles_1h=list(c),
        candles_4h=list(c),
        stop_distance_percent=1.0,
        reward_risk=1.8,
        spread_percent=0.02,
    )


def test_capture_is_non_authoritative_and_contains_decision_evidence():
    record = capture_entry_v2("LINKUSDT", facts(), captured_at="2026-09-17T08:00:00+03:00")
    data = record.to_dict()
    assert data["schema_version"] == 2
    assert len(data["capture_id"]) == 24
    assert data["symbol"] == "LINKUSDT"
    assert data["legacy_result"]["scalp_score"] == 68
    assert data["entry_scenario"]["market"]["5m_bias"]
    assert set(data["entry_scenario"]["structure"]["multi_candle_by_timeframe"]) == {"5m", "15m", "1h", "4h"}
    assert data["v2_decision"]["decision"].startswith(("APPROVED_", "REJECT_"))
    assert all(tf in data["closed_candle_windows"] for tf in ("5m", "15m", "1h", "4h"))


def test_capture_id_is_deterministic_for_same_observation():
    first = capture_entry_v2("LINKUSDT", facts(), captured_at="2026-09-17T08:00:00+03:00")
    second = capture_entry_v2("LINKUSDT", facts(), captured_at="2026-09-17T08:00:00+03:00")
    assert first.capture_id == second.capture_id


def test_captured_scenario_can_be_replayed_without_raw_market_access():
    record = capture_entry_v2("LINKUSDT", facts(), captured_at="2026-09-17T08:00:00+03:00")
    original = record.v2_decision["decision"]
    replayed = replay_captured(record)
    assert replayed.decision == original
    assert replayed.trade_mode == record.v2_decision["trade_mode"]
    assert replayed.setup_type == record.v2_decision["setup_type"]


def test_capture_summary_is_compact_and_preserves_candle_patterns():
    record = capture_entry_v2("LINKUSDT", facts(), captured_at="2026-09-17T08:00:00+03:00")
    summary = capture_summary(record)
    assert summary["symbol"] == "LINKUSDT"
    assert summary["capture_id"] == record.capture_id
    assert summary["legacy_trade_mode"] == "SCALP"
    assert summary["legacy_score"] == 68
    assert summary["v2_trade_mode"] == "SCALP"
    assert summary["candle_patterns_5m"]
    assert summary["candle_patterns_1h"]


def test_capture_does_not_mutate_legacy_input():
    legacy = legacy_reversal()
    market_facts = facts()
    before = repr(legacy)
    capture_entry_v2("ADAUSDT", market_facts)
    assert repr(legacy) == before
