from core.brain_metrics import BrainMetrics


def test_brain_metrics_counts_agreement_and_authoritative_override():
    metrics = BrainMetrics()
    metrics.record(brain_action="SELL", policy_exit=True, review_required=False)
    metrics.record(brain_action="HOLD", policy_exit=True, review_required=False)
    metrics.record(brain_action="HOLD", policy_exit=False, review_required=False)

    assert metrics.snapshot() == {
        "total_brain_decisions": 3,
        "agreements": 2,
        "disagreements": 1,
        "exit_policy_sells": 2,
        "brain_suggested_sells": 1,
        "brain_suggested_holds": 2,
        "brain_suggested_reviews": 0,
        "authoritative_overrides": 1,
    }


def test_review_decision_is_not_counted_as_agreement_or_disagreement():
    metrics = BrainMetrics()
    metrics.record(brain_action="REVIEW", policy_exit=True, review_required=True)

    assert metrics.snapshot()["total_brain_decisions"] == 1
    assert metrics.snapshot()["agreements"] == 0
    assert metrics.snapshot()["disagreements"] == 0
    assert metrics.snapshot()["authoritative_overrides"] == 0
