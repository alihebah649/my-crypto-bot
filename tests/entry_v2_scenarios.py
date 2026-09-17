"""Deterministic market scenarios for the Entry v2 acceptance contract.

These fixtures intentionally describe the *decision inputs* rather than the
implementation.  Production entry logic should consume equivalent market
facts and return one of the documented rejection/approval states.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class EntryScenario:
    name: str
    expected_decision: str
    trade_mode: str = "SCALP"
    setup_type: str | None = None
    market: dict[str, Any] = field(default_factory=dict)
    structure: dict[str, Any] = field(default_factory=dict)
    trigger: dict[str, Any] = field(default_factory=dict)
    execution: dict[str, Any] = field(default_factory=dict)
    risk: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


SCENARIOS = {
    "falling_knife": EntryScenario(
        name="falling_knife",
        expected_decision="REJECT_COUNTERTREND",
        market={
            "5m_bias": "RECOVERY",
            "15m_bias": "BEARISH",
            "1h_bias": "BEARISH",
            "4h_bias": "BEARISH",
            "btc_guard": "PASS",
        },
        structure={
            "location_at_support": True,
            "selling_pressure_weakening": False,
            "higher_low": False,
            "reclaim": False,
        },
        trigger={
            "rsi_recovering": True,
            "bullish_body": True,
            "bullish_pattern": "BULLISH_ENGULFING",
            "confirmed_reversal": False,
            "volume_ratio_5m": 1.05,
        },
        execution={"closed_candle": True, "spread_percent": 0.02},
        risk={"stop_distance_percent": 1.8, "reward_risk": 1.4},
        metadata={"legacy_score": 82, "legacy_recovery_confirmation": True},
    ),
    "fake_recovery": EntryScenario(
        name="fake_recovery",
        expected_decision="REJECT_NO_RECLAIM",
        market={
            "5m_bias": "RECOVERY",
            "15m_bias": "NEUTRAL",
            "1h_bias": "NEUTRAL",
            "4h_bias": "NEUTRAL",
            "btc_guard": "PASS",
        },
        structure={
            "location_at_support": True,
            "selling_pressure_weakening": True,
            "higher_low": False,
            "reclaim": False,
        },
        trigger={
            "rsi_recovering": True,
            "bullish_body": True,
            "bullish_pattern": "BULLISH_ENGULFING",
            "confirmed_reversal": False,
            "volume_ratio_5m": 1.18,
        },
        execution={"closed_candle": True, "spread_percent": 0.02},
        risk={"stop_distance_percent": 1.2, "reward_risk": 1.5},
        metadata={"legacy_score": 78, "legacy_recovery_confirmation": True},
    ),
    "valid_reversal": EntryScenario(
        name="valid_reversal",
        expected_decision="APPROVED_SCALP",
        setup_type="REVERSAL",
        market={
            "5m_bias": "BULLISH",
            "15m_bias": "NEUTRAL_SUPPORT",
            "1h_bias": "NEUTRAL",
            "4h_bias": "BULLISH",
            "btc_guard": "PASS",
        },
        structure={
            "location_at_support": True,
            "selling_pressure_weakening": True,
            "higher_low": True,
            "reclaim": True,
            "reclaimed_level_percent": 0.35,
        },
        trigger={
            "rsi_recovering": True,
            "bullish_body": True,
            "bullish_pattern": "BULLISH_ENGULFING",
            "confirmed_reversal": True,
            "volume_ratio_5m": 1.32,
        },
        execution={"closed_candle": True, "spread_percent": 0.02},
        risk={"stop_distance_percent": 0.9, "reward_risk": 2.1},
        metadata={"legacy_score": 66},
    ),
    "valid_continuation": EntryScenario(
        name="valid_continuation",
        expected_decision="APPROVED_SCALP",
        setup_type="CONTINUATION",
        market={
            "5m_bias": "BULLISH",
            "15m_bias": "BULLISH",
            "1h_bias": "BULLISH",
            "4h_bias": "BULLISH",
            "btc_guard": "PASS",
        },
        structure={
            "location_pullback": True,
            "pullback_holds": True,
            "higher_low": True,
            "reclaim": True,
            "continuation_break": True,
        },
        trigger={
            "rsi_recovering": False,
            "bullish_body": True,
            "bullish_pattern": "BULLISH_BREAKOUT",
            "confirmed_reversal": False,
            "volume_ratio_5m": 1.41,
        },
        execution={"closed_candle": True, "spread_percent": 0.015},
        risk={"stop_distance_percent": 0.8, "reward_risk": 2.4},
        metadata={"legacy_score": 69},
    ),
    "wide_stop": EntryScenario(
        name="wide_stop",
        expected_decision="REJECT_STOP_TOO_WIDE",
        market={
            "5m_bias": "BULLISH",
            "15m_bias": "BULLISH_SUPPORT",
            "1h_bias": "BULLISH",
            "4h_bias": "BULLISH",
            "btc_guard": "PASS",
        },
        structure={
            "location_at_support": True,
            "selling_pressure_weakening": True,
            "higher_low": True,
            "reclaim": True,
        },
        trigger={
            "rsi_recovering": True,
            "bullish_body": True,
            "bullish_pattern": "BULLISH_ENGULFING",
            "confirmed_reversal": True,
            "volume_ratio_5m": 1.35,
        },
        execution={"closed_candle": True, "spread_percent": 0.02},
        risk={"stop_distance_percent": 4.2, "reward_risk": 2.0},
        metadata={"legacy_score": 76},
    ),
    "low_reward": EntryScenario(
        name="low_reward",
        expected_decision="REJECT_LOW_REWARD",
        market={
            "5m_bias": "BULLISH",
            "15m_bias": "BULLISH_SUPPORT",
            "1h_bias": "BULLISH",
            "4h_bias": "BULLISH",
            "btc_guard": "PASS",
        },
        structure={
            "location_at_support": True,
            "selling_pressure_weakening": True,
            "higher_low": True,
            "reclaim": True,
        },
        trigger={
            "rsi_recovering": True,
            "bullish_body": True,
            "bullish_pattern": "BULLISH_ENGULFING",
            "confirmed_reversal": True,
            "volume_ratio_5m": 1.27,
        },
        execution={"closed_candle": True, "spread_percent": 0.02},
        risk={"stop_distance_percent": 1.0, "reward_risk": 0.65},
        metadata={"legacy_score": 79},
    ),
    "reentry_trap": EntryScenario(
        name="reentry_trap",
        expected_decision="REJECT_REENTRY_LOCK",
        market={
            "5m_bias": "RECOVERY",
            "15m_bias": "SUPPORT",
            "1h_bias": "NEUTRAL",
            "4h_bias": "NEUTRAL",
            "btc_guard": "PASS",
        },
        structure={
            "location_at_support": True,
            "selling_pressure_weakening": True,
            "higher_low": False,
            "reclaim": False,
        },
        trigger={
            "rsi_recovering": True,
            "bullish_body": True,
            "bullish_pattern": "BULLISH_ENGULFING",
            "confirmed_reversal": False,
            "volume_ratio_5m": 1.08,
        },
        execution={"closed_candle": True, "spread_percent": 0.02},
        risk={"stop_distance_percent": 1.1, "reward_risk": 1.7},
        metadata={
            "prior_exit": "STOP_LOSS",
            "prior_context_fingerprint_same": True,
            "legacy_score": 74,
        },
    ),
    "reentry_new_structure": EntryScenario(
        name="reentry_new_structure",
        expected_decision="APPROVED_SCALP",
        setup_type="REVERSAL",
        market={
            "5m_bias": "BULLISH",
            "15m_bias": "SUPPORT",
            "1h_bias": "NEUTRAL",
            "4h_bias": "BULLISH",
            "btc_guard": "PASS",
        },
        structure={
            "location_at_support": True,
            "selling_pressure_weakening": True,
            "higher_low": True,
            "reclaim": True,
            "new_structure_after_prior_stop": True,
        },
        trigger={
            "rsi_recovering": True,
            "bullish_body": True,
            "bullish_pattern": "BULLISH_BREAKOUT",
            "confirmed_reversal": True,
            "volume_ratio_5m": 1.46,
        },
        execution={"closed_candle": True, "spread_percent": 0.02},
        risk={"stop_distance_percent": 0.95, "reward_risk": 2.2},
        metadata={
            "prior_exit": "STOP_LOSS",
            "prior_context_fingerprint_same": False,
            "legacy_score": 68,
        },
    ),
    "score_trap": EntryScenario(
        name="score_trap",
        expected_decision="REJECT_NO_RECLAIM",
        market={
            "5m_bias": "RECOVERY",
            "15m_bias": "SUPPORT",
            "1h_bias": "NEUTRAL",
            "4h_bias": "NEUTRAL",
            "btc_guard": "PASS",
        },
        structure={
            "location_at_support": True,
            "selling_pressure_weakening": True,
            "higher_low": False,
            "reclaim": False,
        },
        trigger={
            "rsi_recovering": True,
            "bullish_body": True,
            "bullish_pattern": "BULLISH_ENGULFING",
            "confirmed_reversal": False,
            "volume_ratio_5m": 1.24,
        },
        execution={"closed_candle": True, "spread_percent": 0.02},
        risk={"stop_distance_percent": 1.0, "reward_risk": 1.8},
        metadata={"legacy_score": 82},
    ),
    "low_score_valid": EntryScenario(
        name="low_score_valid",
        expected_decision="APPROVED_SCALP",
        setup_type="REVERSAL",
        market={
            "5m_bias": "BULLISH",
            "15m_bias": "SUPPORT",
            "1h_bias": "NEUTRAL",
            "4h_bias": "NEUTRAL",
            "btc_guard": "PASS",
        },
        structure={
            "location_at_support": True,
            "selling_pressure_weakening": True,
            "higher_low": True,
            "reclaim": True,
        },
        trigger={
            "rsi_recovering": True,
            "bullish_body": True,
            "bullish_pattern": "BULLISH_ENGULFING",
            "confirmed_reversal": True,
            "volume_ratio_5m": 1.22,
        },
        execution={"closed_candle": True, "spread_percent": 0.02},
        risk={"stop_distance_percent": 1.1, "reward_risk": 1.7},
        metadata={"legacy_score": 66},
    ),
    "btc_guard": EntryScenario(
        name="btc_guard",
        expected_decision="REJECT_BTC_GUARD",
        market={
            "5m_bias": "BULLISH",
            "15m_bias": "BULLISH_SUPPORT",
            "1h_bias": "BULLISH",
            "4h_bias": "BULLISH",
            "btc_guard": "FAIL",
        },
        structure={
            "location_at_support": True,
            "selling_pressure_weakening": True,
            "higher_low": True,
            "reclaim": True,
        },
        trigger={
            "rsi_recovering": True,
            "bullish_body": True,
            "bullish_pattern": "BULLISH_ENGULFING",
            "confirmed_reversal": True,
            "volume_ratio_5m": 1.40,
        },
        execution={"closed_candle": True, "spread_percent": 0.02},
        risk={"stop_distance_percent": 1.0, "reward_risk": 2.0},
        metadata={"legacy_score": 85},
    ),
}


EXPECTED_DECISIONS = {
    name: scenario.expected_decision for name, scenario in SCENARIOS.items()
}
