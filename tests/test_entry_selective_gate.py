from core.entry_selective_gate import (
    BEAR_SCALP_MIN_VOLUME_RATIO,
    RSI_PRESSURE_THRESHOLD,
    selective_entry_veto,
)


def _shadow(failed_gate="SELLER_PRESSURE_NOT_INVALIDATED", **adaptive_overrides):
    adaptive = {
        "regime": "BEAR",
        "five_m_bias": "BEARISH",
        "volume_ratio_5m": 0.918,
        "classification": "BEAR_RECOVERY",
    }
    adaptive.update(adaptive_overrides)
    return {
        "trade_mode": "SCALP",
        "failed_gate": failed_gate,
        "adaptive_scalp_shadow": adaptive,
    }


def test_hbar_bear_scalp_pressure_combination_is_vetoed():
    strategy = {
        "trade_mode": "SCALP",
        "scalp_confirmed_reversal": True,
        "scalp_recovery_confirmation": True,
        "rsi5m": 39.8644,
    }
    assert selective_entry_veto(
        strategy,
        _shadow(),
        trade_mode="SCALP",
    ) == "V2_BEAR_SCALP_5M_PRESSURE_LOW_VOLUME"


def test_bear_scalp_veto_reuses_existing_v2_volume_boundary():
    strategy = {"rsi5m": 39.8644}
    assert BEAR_SCALP_MIN_VOLUME_RATIO == 1.0
    assert selective_entry_veto(
        strategy,
        _shadow(volume_ratio_5m=1.0),
        trade_mode="SCALP",
    ) is None


def test_bear_scalp_veto_requires_bearish_5m_bias():
    strategy = {"rsi5m": 39.8644}
    assert selective_entry_veto(
        strategy,
        _shadow(five_m_bias="NEUTRAL"),
        trade_mode="SCALP",
    ) is None


def test_bear_scalp_veto_requires_adaptive_bear_regime():
    strategy = {"rsi5m": 39.8644}
    assert selective_entry_veto(
        strategy,
        _shadow(regime="BULL"),
        trade_mode="SCALP",
    ) is None


def test_bear_scalp_veto_is_limited_to_seller_pressure_rejection():
    strategy = {"rsi5m": 39.8644}
    assert selective_entry_veto(
        strategy,
        _shadow(failed_gate="STRUCTURAL_RECLAIM_NOT_CONFIRMED"),
        trade_mode="SCALP",
    ) is None


def test_bear_scalp_veto_does_not_match_the_recent_algo_winner_profile():
    strategy = {"rsi5m": 48.2830}
    assert selective_entry_veto(
        strategy,
        _shadow(five_m_bias="NEUTRAL", volume_ratio_5m=1.6383),
        trade_mode="SCALP",
    ) is None


def test_existing_rsi_pressure_vetoes_remain_unchanged():
    strategy = {"rsi5m": RSI_PRESSURE_THRESHOLD}
    assert selective_entry_veto(
        strategy,
        {"failed_gate": "SELLER_PRESSURE_NOT_INVALIDATED"},
        trade_mode="SCALP",
    ) == "V2_SELLER_PRESSURE_RSI_PRESSURE"
    assert selective_entry_veto(
        strategy,
        {"failed_gate": "STRUCTURAL_RECLAIM_NOT_CONFIRMED"},
        trade_mode="SCALP",
    ) == "V2_STRUCTURAL_RECLAIM_RSI_PRESSURE"
    assert selective_entry_veto(
        strategy,
        {"failed_gate": "SWING_STRUCTURE_OR_HTF_ALIGNMENT_MISSING"},
        trade_mode="SWING",
    ) == "V2_SWING_STRUCTURE_RSI_PRESSURE"


def test_non_matching_low_rsi_seller_rejection_stays_advisory():
    strategy = {"rsi5m": 39.0}
    shadow = _shadow(regime="TRANSITION")
    assert selective_entry_veto(strategy, shadow, trade_mode="SCALP") is None
