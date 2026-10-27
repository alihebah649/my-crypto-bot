"""Regression tests for fail-closed Brain entry authority wiring."""
from __future__ import annotations

from types import SimpleNamespace

import shadow_main


def test_missing_brain_context_is_rejected_and_persisted(monkeypatch):
    runtime = SimpleNamespace(last_entry_diagnostics={})

    class CaptureStore:
        def __init__(self):
            self.records = []
            self.last_error = None

        def append(self, record):
            self.records.append(dict(record))
            return True

    store = CaptureStore()
    monkeypatch.setattr(shadow_main, "runtime", runtime)
    monkeypatch.setattr(shadow_main, "_brain_authority_store", store)

    allowed = shadow_main._brain_authority_entry_gate(
        "INCOMPLETEUSDT",
        {"signal": "BUY", "score": 95},
        "SCALP",
    )

    assert allowed is False
    trace = runtime.last_entry_diagnostics["INCOMPLETEUSDT"]
    record = trace["brain_authority_by_mode"]["SCALP"]
    assert record["decision_state"] == "REJECTED_INCOMPLETE_CONTEXT"
    assert record["reason"] == "BRAIN_CONTEXT_INCOMPLETE"
    assert record["brain_reason"] == "BRAIN_CONTEXT_INCOMPLETE"
    assert record["allowed"] is False
    assert trace["result"] == "REJECTED_BRAIN_AUTHORITY"
    assert trace["execution"] == "NOT_RUN"

    assert len(store.records) == 1
    persisted = store.records[0]
    assert persisted["stage"] == "ENTRY_GATE"
    assert persisted["symbol"] == "INCOMPLETEUSDT"
    assert persisted["trade_mode"] == "SCALP"
    assert persisted["allowed"] is False
    assert persisted["context"]["context_complete"] is False
    assert persisted["context"]["missing_required_context"] == [
        "scalp_reversal_or_recovery_confirmation"
    ]
    assert persisted["observed_at"] > 0
