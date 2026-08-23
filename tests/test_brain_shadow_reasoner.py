from core.brain_reasoning import BrainDecision
from core.brain_shadow_reasoner import ShadowAIReasoner


class FakeProvider:
    def reason(self, context):
        return BrainDecision("HOLD", 0.73, "SHADOW_TEST")


def test_shadow_reasoner_returns_provider_decision_without_execution():
    context = {"symbol": "BTCUSDT", "exit_policy": {"decision": "HOLD"}}
    result = ShadowAIReasoner(FakeProvider()).evaluate_shadow(context)

    assert result.shadow_only is True
    assert result.ai_decision.action == "HOLD"
    assert result.ai_decision.confidence == 0.73
    assert context["symbol"] == "BTCUSDT"


def test_shadow_reasoner_uses_same_reasoning_contract():
    reasoner = ShadowAIReasoner(FakeProvider())
    decision = reasoner.decide({"symbol": "ETHUSDT"})
    assert decision.reason == "SHADOW_TEST"
