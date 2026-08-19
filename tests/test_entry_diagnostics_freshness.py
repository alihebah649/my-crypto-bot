"""Regression coverage for per-symbol Paper BUY diagnostic freshness."""
from __future__ import annotations

import shadow_main


def test_rejected_buy_diagnostic_cannot_reuse_prior_fill_trace(monkeypatch):
    trace = {
        "symbol": "ALGOUSDT",
        "execution": "FILLED",
        "execution_outcome": {"exchange_order_id": "PAPER-OLD"},
        "facade": "CALLED",
        "facade_diagnostic": {"result": "POSITION_COMMITTED"},
        "position_id": "POS-OLD",
        "result": "REJECTED_EXISTING_POSITION",
    }
    monkeypatch.setattr(shadow_main.runtime, "last_entry_diagnostics", {"ALGOUSDT": trace})

    shadow_main._sanitize_entry_diagnostics()

    assert trace["result"] == "REJECTED_EXISTING_POSITION"
    assert trace["execution"] == "NOT_RUN"
    assert trace["execution_outcome"] is None
    assert trace["facade"] == "NOT_RUN"
    assert "facade_diagnostic" not in trace
    assert "position_id" not in trace


def test_successful_position_trace_is_not_sanitized(monkeypatch):
    trace = {
        "symbol": "ATOMUSDT",
        "execution": "FILLED",
        "execution_outcome": {"exchange_order_id": "PAPER-NEW"},
        "facade": "CALLED",
        "position_id": "POS-NEW",
        "result": "POSITION_COMMITTED",
    }
    monkeypatch.setattr(shadow_main.runtime, "last_entry_diagnostics", {"ATOMUSDT": trace})

    shadow_main._sanitize_entry_diagnostics()

    assert trace["execution"] == "FILLED"
    assert trace["execution_outcome"]["exchange_order_id"] == "PAPER-NEW"
    assert trace["facade"] == "CALLED"
    assert trace["position_id"] == "POS-NEW"
