from core.brain_reasoning import BrainDecision, DeterministicBrainReasoner, BrainReasoner


def test_deterministic_reasoner_respects_authoritative_exit():
    decision = DeterministicBrainReasoner().decide({"exit_policy": {"decision": "EXIT"}})
    assert isinstance(decision, BrainDecision)
    assert decision.action == "EXIT"
    assert decision.confidence == 1.0


def test_deterministic_reasoner_defaults_to_hold():
    decision = DeterministicBrainReasoner().decide({"exit_policy": {"decision": "HOLD"}})
    assert decision.action == "HOLD"


def test_reasoner_is_an_interface():
    assert hasattr(BrainReasoner, "decide")
