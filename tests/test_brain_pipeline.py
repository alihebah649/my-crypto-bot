from core.brain_pipeline import BrainDecisionPipeline
from core.brain_reasoning import DeterministicBrainReasoner


def test_pipeline_preserves_authoritative_exit():
    result = BrainDecisionPipeline(DeterministicBrainReasoner()).evaluate(
        {"exit_policy": {"decision": "EXIT"}}
    )
    assert result.brain_decision.action == "EXIT"
    assert result.final_action == "EXIT"
    assert result.authority == "EXIT_POLICY"


def test_pipeline_does_not_execute_or_mutate_context():
    context = {"exit_policy": {"decision": "HOLD"}, "symbol": "BTCUSDT"}
    result = BrainDecisionPipeline(DeterministicBrainReasoner()).evaluate(context)
    assert result.final_action == "HOLD"
    assert context == {"exit_policy": {"decision": "HOLD"}, "symbol": "BTCUSDT"}
