from __future__ import annotations

import dual_mode_strategy


def candle(open_price: float, high: float, low: float, close: float, volume: float = 100.0) -> dict:
    return {"open": open_price, "high": high, "low": low, "close": close, "volume": volume}


def candles(count: int = 30) -> list[dict]:
    return [candle(100.0, 101.0, 99.0, 100.0, 100.0) for _ in range(count)]


def test_scalp_rsi_gate_zone_contributes_zero_score(monkeypatch):
    """Expose the RSI calibration gap: gate allows <=55, scoring stops at 45."""
    rsi_value = {"value": 48.66}

    monkeypatch.setattr(
        dual_mode_strategy,
        "calculate_rsi",
        lambda prices, period=14: rsi_value["value"],
    )
    monkeypatch.setattr(
        dual_mode_strategy,
        "calculate_bollinger",
        lambda candles, period=20, deviations=2.0: (
            (95.0, 110.0, 121.0) if len(candles) >= 100 else (99.5, 110.0, 121.0)
        ),
    )
    monkeypatch.setattr(dual_mode_strategy, "_volume_ratio", lambda candles, window=20: 1.127)
    monkeypatch.setattr(dual_mode_strategy, "bullish_pattern", lambda candles: (False, "NEUTRAL", False))
    monkeypatch.setattr(
        dual_mode_strategy,
        "_scalp_recovery_confirmation",
        lambda candles, current_rsi: (True, 2, ["5M_PRICE_RECOVERY", "5M_BULLISH_BODY"]),
    )
    monkeypatch.setattr(
        dual_mode_strategy,
        "analyze_multi_timeframe_context",
        lambda data: {
            "available": True,
            "bias": "NEUTRAL",
            "net": 0,
            "weighted_bull": 0,
            "weighted_bear": 0,
            "weak_countertrend_recovery": False,
            "aligned_bullish": False,
            "higher_timeframes_bearish": False,
            "higher_timeframes_bullish": False,
            "frames": {},
        },
    )

    kwargs = {
        "symbol": "FETUSDT",
        "ticker": {"lastPrice": "100.0"},
        "candles_15m": candles(130),
        "candles_5m": candles(30),
    }

    in_gate_zone = dual_mode_strategy.score_symbol(**kwargs)

    # The same setup, moved just below the scoring boundary, gains the
    # 5m RSI recovery-zone points while remaining inside the entry gate.
    rsi_value["value"] = 44.0
    below_score_boundary = dual_mode_strategy.score_symbol(**kwargs)

    assert in_gate_zone["scalp_gate"] is True
    assert below_score_boundary["scalp_gate"] is True
    assert in_gate_zone["rsi5m"] == 48.66
    assert below_score_boundary["rsi5m"] == 44.0
    assert in_gate_zone["scalp_score"] == 34
    assert below_score_boundary["scalp_score"] == 44
    assert below_score_boundary["scalp_score"] - in_gate_zone["scalp_score"] == 10
    assert "5M_RSI_RECOVERY_ZONE" not in in_gate_zone["scalp_reasons"]
    assert "5M_RSI_RECOVERY_ZONE" in below_score_boundary["scalp_reasons"]
