from core.brain_decision_record_factory import build_brain_decision_record
from core.brain_pipeline import BrainDecisionPipeline
from core.brain_reasoning import DeterministicBrainReasoner


def test_factory_records_pipeline_result_and_fingerprint():
    context = {
        "symbol": "BTCUSDT",
        "trade_mode": "SCALP",
        "exit_policy": {"decision": "EXIT"},
    }
    result = BrainDecisionPipeline(DeterministicBrainReasoner()).evaluate(context)
    record = build_brain_decision_record(context, result, timestamp=123.0)

    assert record.timestamp == 123.0
    assert record.symbol == "BTCUSDT"
    assert record.trade_mode == "SCALP"
    assert record.brain_action == "EXIT"
    assert record.policy_action == "EXIT"
    assert record.final_action == "EXIT"
    assert record.authority == "EXIT_POLICY"
    assert record.brain_agrees_with_policy is True
    assert record.context_fingerprint


def test_factory_does_not_mutate_context():
    context = {"symbol": "ETHUSDT", "exit_policy": {"decision": "HOLD"}}
    original = {"symbol": "ETHUSDT", "exit_policy": {"decision": "HOLD"}}
    result = BrainDecisionPipeline(DeterministicBrainReasoner()).evaluate(context)
    build_brain_decision_record(context, result, timestamp=456.0)
    assert context == original
