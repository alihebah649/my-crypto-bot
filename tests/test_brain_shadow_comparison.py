from core.brain_reasoning import BrainDecision
from core.brain_shadow_comparison import compare_shadow_decisions


def test_shadow_comparison_records_agreement_and_policy():
    context = {"symbol": "BTCUSDT", "exit_policy": {"decision": "HOLD"}}
    decision = BrainDecision("HOLD", 0.8, "RECOVERY")
    result = compare_shadow_decisions(context, decision, decision)

    assert result.brain_agrees is True
    assert result.ai_agrees_with_policy is True
    assert result.deterministic_agrees_with_policy is True
    assert result.disagreement_reason is None
    assert result.authority == "POLICY"


def test_shadow_comparison_records_disagreement_without_changing_authority():
    context = {"symbol": "ETHUSDT", "exit_policy": {"decision": "EXIT"}}
    deterministic = BrainDecision("EXIT", 1.0, "POLICY")
    ai = BrainDecision("HOLD", 0.9, "RECOVERY")
    result = compare_shadow_decisions(context, deterministic, ai)

    assert result.brain_agrees is False
    assert result.ai_agrees_with_policy is False
    assert result.deterministic_agrees_with_policy is True
    assert result.disagreement_reason == "AI=HOLD;DETERMINISTIC=EXIT"
    assert result.authority == "POLICY"
