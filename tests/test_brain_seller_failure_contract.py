from __future__ import annotations

from core.brain_authority import GuardedBrainAuthority


def _strategy(*, seller_failure_confirmed: bool) -> dict:
    return {
        "scalp_signal": "BUY",
        "scalp_score": 70.0,
        "score": 70.0,
        "trade_mode": "SCALP",
        "scalp_confirmed_reversal": True,
        "scalp_recovery_confirmation": True,
        "scalp_structural_confirmation": True,
        "volume_ratio_5m": 1.20,
        "seller_failure_confirmed": seller_failure_confirmed,
        "mtf_net": -1.0,
        "mtf_weighted_bull": 0.0,
        "mtf_weighted_bear": 1.0,
        "mtf_higher_timeframes_bearish": False,
        "mtf_timeframe_bias": {"1h": "NEUTRAL", "4h": "NEUTRAL"},
    }


def test_guarded_brain_accepts_bear_scalp_when_seller_failure_is_confirmed() -> None:
    result = GuardedBrainAuthority().evaluate_entry(
        "FETUSDT",
        _strategy(seller_failure_confirmed=True),
        trade_mode="SCALP",
        market_regime="BEAR",
    )

    assert result.allowed is True
    assert result.brain_action == "BUY"
    assert result.brain_reason == "BEAR_COUNTERTREND_SCALP_CONFIRMED"


def test_guarded_brain_still_blocks_bear_scalp_without_seller_failure() -> None:
    result = GuardedBrainAuthority().evaluate_entry(
        "FETUSDT",
        _strategy(seller_failure_confirmed=False),
        trade_mode="SCALP",
        market_regime="BEAR",
    )

    assert result.allowed is False
    assert result.brain_action == "HOLD"
    assert result.brain_reason == "BEAR_SELLER_FAILURE_NOT_CONFIRMED"
