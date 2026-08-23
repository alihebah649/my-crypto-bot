from core.brain_decision_record import BrainDecisionRecord


def test_decision_record_is_auditable_and_immutable():
    record = BrainDecisionRecord(
        timestamp=1.0,
        context_fingerprint="abc123",
        symbol="BTCUSDT",
        trade_mode="SCALP",
        brain_action="HOLD",
        confidence=0.82,
        reason="RECOVERY_STRONG",
        policy_action="EXIT",
        final_action="EXIT",
        authority="POLICY",
        brain_agrees_with_policy=False,
        context={"age_minutes": 121},
    )

    data = record.to_dict()
    assert data["context_fingerprint"] == "abc123"
    assert data["final_action"] == "EXIT"
    assert data["brain_agrees_with_policy"] is False

    try:
        record.final_action = "HOLD"
    except Exception:
        pass
    else:
        raise AssertionError("BrainDecisionRecord must be immutable")
