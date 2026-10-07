from __future__ import annotations

from engine import entry_v2_adapter as adapter
from engine.entry_v2_adapter import EntryV2MarketFacts, build_entry_scenario


def _fake_context(patterns=()):
    return {
        "bias": "BULLISH",
        "strength": 4,
        "bull_score": 8,
        "bear_score": 2,
        "patterns": list(patterns),
        "bearish_warning": False,
    }


def test_fifteen_minute_higher_low_counts_as_structural_higher_low(monkeypatch):
    contexts = {
        "5m": _fake_context(["FOUR_C_BEAR_TO_BULL_REVERSAL"]),
        "15m": _fake_context(["7C_HIGHER_LOW_STRUCTURE"]),
        "1h": _fake_context(),
        "4h": _fake_context(),
    }

    monkeypatch.setattr(
        adapter,
        "analyze_multi_timeframe_context",
        lambda _candles: {
            "available": True,
            "bias": "BULL",
            "net": 8,
            "weighted_bull": 20,
            "weighted_bear": 12,
            "frames": {
                "5m": {"bias": "BULLISH"},
                "15m": {"bias": "NEUTRAL"},
                "1h": {"bias": "BULLISH"},
                "4h": {"bias": "BULLISH"},
            },
        },
    )
    # Avoid coupling the test to the concrete candle analyzers by replacing
    # them with deterministic contexts in timeframe order.
    candle_map_calls = iter(adapter.TIMEFRAMES)
    monkeypatch.setattr(
        adapter,
        "analyze_multi_candle_context",
        lambda _candles: contexts[next(candle_map_calls)],
    )

    facts = EntryV2MarketFacts(
        legacy_result={
            "trade_mode": "SCALP",
            "scalp_signal": "BUY",
            "score": 67,
            "scalp_score": 67,
            "scalp_confirmed_reversal": True,
            "scalp_recovery_confirmation": True,
            "scalp_reasons": ["15M_BOLLINGER_LOWER_SUPPORT"],
            "volume_ratio_5m": 1.3,
        },
        candles_5m=[{"close": 1}, {"close": 1}, {"close": 1}],
        candles_15m=[{"close": 1}, {"close": 1}, {"close": 1}],
    )

    scenario = build_entry_scenario(facts)

    assert scenario["structure"]["higher_low"] is True
    assert "15m" in scenario["structure"]["higher_low_timeframes"]
