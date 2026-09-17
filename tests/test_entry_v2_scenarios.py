from __future__ import annotations

import pytest

from tests.entry_v2_scenarios import EXPECTED_DECISIONS, SCENARIOS


REJECTION_PREFIX = "REJECT_"
APPROVALS = {"APPROVED_SCALP", "APPROVED_SWING"}


def test_entry_v2_scenario_catalog_is_nonempty_and_unique():
    assert len(SCENARIOS) >= 10
    assert len(SCENARIOS) == len({scenario.name for scenario in SCENARIOS.values()})
    assert set(EXPECTED_DECISIONS) == set(SCENARIOS)


def test_entry_v2_expected_states_are_valid():
    valid_states = APPROVALS | {
        "REJECT_BTC_GUARD",
        "REJECT_COUNTERTREND",
        "REJECT_NO_LOCATION",
        "REJECT_NO_SELLER_FAILURE",
        "REJECT_NO_RECLAIM",
        "REJECT_NO_VOLUME_CONFIRM",
        "REJECT_OVEREXTENDED",
        "REJECT_STOP_TOO_WIDE",
        "REJECT_LOW_REWARD",
        "REJECT_REENTRY_LOCK",
        "REJECT_DATA_UNAVAILABLE",
    }
    assert set(EXPECTED_DECISIONS.values()) <= valid_states


@pytest.mark.parametrize("scenario_name,scenario", SCENARIOS.items())
def test_every_scenario_has_the_required_decision_inputs(scenario_name, scenario):
    assert scenario.name == scenario_name
    assert scenario.expected_decision
    assert scenario.market["btc_guard"] in {"PASS", "FAIL"}
    assert scenario.execution["closed_candle"] is True
    assert scenario.execution["spread_percent"] >= 0
    assert scenario.trigger["volume_ratio_5m"] > 0
    assert scenario.risk["stop_distance_percent"] > 0
    assert scenario.risk["reward_risk"] > 0


@pytest.mark.parametrize(
    "scenario_name",
    ["falling_knife", "fake_recovery", "score_trap"],
)
def test_rejection_scenarios_are_not_allowed_to_pass_by_score_alone(scenario_name):
    scenario = SCENARIOS[scenario_name]
    assert scenario.metadata["legacy_score"] >= 65
    assert scenario.expected_decision.startswith(REJECTION_PREFIX)


def test_valid_reversal_proves_score_can_be_below_the_legacy_swing_threshold():
    scenario = SCENARIOS["low_score_valid"]
    assert scenario.metadata["legacy_score"] == 66
    assert scenario.expected_decision == "APPROVED_SCALP"
    assert scenario.setup_type == "REVERSAL"


def test_reentry_contract_distinguishes_same_context_from_new_structure():
    trapped = SCENARIOS["reentry_trap"]
    fresh = SCENARIOS["reentry_new_structure"]

    assert trapped.metadata["prior_context_fingerprint_same"] is True
    assert trapped.expected_decision == "REJECT_REENTRY_LOCK"

    assert fresh.metadata["prior_context_fingerprint_same"] is False
    assert fresh.structure["new_structure_after_prior_stop"] is True
    assert fresh.expected_decision == "APPROVED_SCALP"


def test_falling_knife_requires_structure_not_recovery_only():
    scenario = SCENARIOS["falling_knife"]
    assert scenario.trigger["rsi_recovering"] is True
    assert scenario.trigger["bullish_body"] is True
    assert scenario.structure["higher_low"] is False
    assert scenario.structure["reclaim"] is False
    assert scenario.expected_decision == "REJECT_COUNTERTREND"
