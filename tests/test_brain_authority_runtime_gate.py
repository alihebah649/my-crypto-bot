"""Regression tests for fail-closed Brain entry authority wiring."""
from __future__ import annotations

from types import SimpleNamespace

import shadow_main


def test_missing_brain_context_is_rejected_instead_of_bypassing_gate(monkeypatch):
    runtime = SimpleNamespace(last_entry_diagnostics={})
    monkeypatch.setattr(shadow_main, "runtime", runtime)

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
    assert record["allowed"] is False
    assert trace["result"] == "REJECTED_BRAIN_AUTHORITY"
    assert trace["execution"] == "NOT_RUN"
