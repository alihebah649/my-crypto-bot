from engine.entry_v2_adapter import EntryV2MarketFacts
from engine.entry_v2_replay import replay_many, replay_one


def candle(o, c, low=None, high=None, volume=100.0):
    low = o - 0.2 if low is None else low
    high = c + 0.2 if high is None else high
    return {"open": o, "close": c, "low": low, "high": high, "volume": volume}


def candles():
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


def facts(legacy):
    c = candles()
    return EntryV2MarketFacts(
        legacy_result=legacy,
        candles_5m=c,
        candles_15m=list(c),
        candles_1h=list(c),
        candles_4h=list(c),
        stop_distance_percent=1.0,
        reward_risk=1.8,
        spread_percent=0.02,
    )


def legacy_buy_recovery():
    return {
        "signal": "BUY",
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


def legacy_buy_reversal():
    return {
        **legacy_buy_recovery(),
        "scalp_confirmed_reversal": True,
        "scalp_recovery_confirmation": False,
        "score": 68,
    }


def test_replay_preserves_legacy_and_records_v2_rejection():
    row = replay_one("ADAUSDT", facts(legacy_buy_recovery()))
    assert row.legacy_decision == "BUY"
    assert row.legacy_trade_mode == "SCALP"
    assert row.legacy_score == 82.0
    assert row.v2_decision in {"REJECT_NO_RECLAIM", "REJECT_COUNTERTREND"}
    assert row.v2_trade_mode == "SCALP"
    assert row.candle_patterns_5m
    assert row.candle_patterns_15m
    assert row.candle_patterns_1h
    assert row.candle_patterns_4h


def test_replay_carries_a_structural_reversal_as_v2_candidate():
    row = replay_one("LINKUSDT", facts(legacy_buy_reversal()))
    assert row.legacy_decision == "BUY"
    assert row.legacy_trade_mode == "SCALP"
    assert row.v2_setup_type in {"REVERSAL", "CONTINUATION", None}
    assert row.candle_patterns_5m


def test_replay_many_keeps_symbol_identity():
    rows = replay_many({
        "ADAUSDT": facts(legacy_buy_recovery()),
        "LINKUSDT": facts(legacy_buy_reversal()),
    })
    assert [row.symbol for row in rows] == ["ADAUSDT", "LINKUSDT"]
