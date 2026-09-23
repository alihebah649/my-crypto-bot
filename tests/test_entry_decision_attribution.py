from core.entry_decision_attribution import build_entry_decision_chain


def test_entry_decision_chain_preserves_v2_rejection_on_an_opened_position():
    record = build_entry_decision_chain(
        {
            "scalp_signal": "BUY",
            "scalp_score": 70,
            "swing_signal": "HOLD",
            "swing_score": 40,
        },
        trade_mode="SCALP",
        brain_record={
            "capture_id": "brain-1",
            "stage": "ENTRY_GATE",
            "allowed": True,
            "brain_action": "BUY",
            "brain_confidence": 70.0,
            "brain_reason": "CONFIRMED_ENTRY",
        },
        v2_record={
            "capture_id": "v2-1",
            "v2_approved": False,
            "v2_decision": "REJECT_NO_VOLUME_CONFIRM",
            "v2_failed_gate": "VOLUME_NOT_CONFIRMING",
        },
        final_approved=True,
        execution_attempted=True,
        position_opened=True,
    )

    assert record["legacy"]["approved"] is True
    assert record["brain_authority"]["evaluated"] is True
    assert record["brain_authority"]["allowed"] is True
    assert record["entry_v2"]["available"] is True
    assert record["entry_v2"]["approved"] is False
    assert record["entry_v2"]["failed_gate"] == "VOLUME_NOT_CONFIRMING"
    assert record["final"]["approved"] is True
    assert record["final"]["position_opened"] is True


def test_entry_decision_chain_marks_incomplete_brain_as_bypassed():
    record = build_entry_decision_chain(
        {"scalp_signal": "BUY", "scalp_score": 68},
        trade_mode="SCALP",
        brain_record={
            "stage": "ENTRY_GATE",
            "decision_state": "BYPASS_INCOMPLETE_CONTEXT",
            "reason": "BRAIN_CONTEXT_INCOMPLETE",
            "allowed": True,
        },
        v2_record={
            "capture_id": "v2-2",
            "v2_approved": True,
            "v2_decision": "APPROVED_SCALP",
        },
        final_approved=True,
        execution_attempted=True,
        position_opened=True,
    )

    assert record["brain_authority"]["evaluated"] is False
    assert record["brain_authority"]["bypassed"] is True
    assert record["brain_authority"]["bypass_reason"] == "BRAIN_CONTEXT_INCOMPLETE"
    assert record["brain_authority"]["allowed"] is True


def test_entry_decision_chain_records_downstream_rejection_separately():
    record = build_entry_decision_chain(
        {"swing_signal": "BUY", "swing_score": 82},
        trade_mode="SWING",
        brain_record={
            "capture_id": "brain-3",
            "stage": "ENTRY_GATE",
            "allowed": True,
            "brain_action": "BUY",
            "brain_confidence": 82.0,
            "brain_reason": "CONFIRMED_ENTRY",
        },
        v2_record={
            "capture_id": "v2-3",
            "v2_approved": True,
            "v2_decision": "APPROVED_SWING",
        },
        final_approved=False,
        execution_attempted=True,
        position_opened=False,
        failed_gate="DOWNSTREAM_OPEN_POSITION",
    )

    assert record["legacy"]["approved"] is True
    assert record["brain_authority"]["allowed"] is True
    assert record["entry_v2"]["approved"] is True
    assert record["final"]["approved"] is False
    assert record["final"]["execution_attempted"] is True
    assert record["final"]["position_opened"] is False
    assert record["final"]["failed_gate"] == "DOWNSTREAM_OPEN_POSITION"
