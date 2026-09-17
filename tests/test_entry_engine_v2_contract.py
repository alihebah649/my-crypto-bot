from entry_v2_scenarios import SCENARIOS
from engine.entry_engine import EntryEngineV2


ENGINE = EntryEngineV2()


def test_all_frozen_scenarios_match_entry_v2_contract():
    for name, scenario in SCENARIOS.items():
        result = ENGINE.evaluate(scenario)
        assert result.decision == scenario.expected_decision, (
            f"{name}: expected {scenario.expected_decision}, got {result.decision}; "
            f"failed_gate={result.failed_gate}; passed={result.passed_gates}"
        )


def test_score_never_overrides_a_failed_hard_gate():
    result = ENGINE.evaluate(SCENARIOS["score_trap"])
    assert result.approved is False
    assert result.decision == "REJECT_NO_RECLAIM"
    assert result.diagnostics["legacy_score_used_as_gate"] is False


def test_low_score_valid_setup_can_be_approved():
    result = ENGINE.evaluate(SCENARIOS["low_score_valid"])
    assert result.approved is True
    assert result.decision == "APPROVED_SCALP"
    assert result.setup_type == "REVERSAL"
    assert result.diagnostics["legacy_score"] == 66
    assert result.diagnostics["legacy_score_used_as_gate"] is False


def test_recovery_cannot_replace_structure():
    result = ENGINE.evaluate(SCENARIOS["fake_recovery"])
    assert result.approved is False
    assert result.decision == "REJECT_NO_RECLAIM"


def test_strong_countertrend_recovery_is_rejected_before_entry_confirmation():
    result = ENGINE.evaluate(SCENARIOS["falling_knife"])
    assert result.approved is False
    assert result.decision == "REJECT_COUNTERTREND"


def test_wide_stop_and_low_reward_are_hard_risk_gates():
    wide_stop = ENGINE.evaluate(SCENARIOS["wide_stop"])
    low_reward = ENGINE.evaluate(SCENARIOS["low_reward"])
    assert wide_stop.decision == "REJECT_STOP_TOO_WIDE"
    assert low_reward.decision == "REJECT_LOW_REWARD"


def test_reentry_lock_requires_new_structure_after_a_stop():
    locked = ENGINE.evaluate(SCENARIOS["reentry_trap"])
    new_structure = ENGINE.evaluate(SCENARIOS["reentry_new_structure"])
    assert locked.decision == "REJECT_REENTRY_LOCK"
    assert new_structure.decision == "APPROVED_SCALP"


def test_valid_continuation_does_not_require_reversal_signal():
    result = ENGINE.evaluate(SCENARIOS["valid_continuation"])
    assert result.approved is True
    assert result.decision == "APPROVED_SCALP"
    assert result.setup_type == "CONTINUATION"
