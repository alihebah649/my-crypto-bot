"""Entry-gate integration regressions for fail-closed Brain authority."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import shadow_main


class RecordingStore:
    def __init__(self):
        self.records = []
        self.last_error = None

    def append(self, record):
        self.records.append(dict(record))
        return True


@pytest.mark.parametrize(
    ("mode", "strategy"),
    [
        (
            "SCALP",
            {
                "trade_mode": "SWING",
                "signal": "BUY",
                "score": 95,
                "swing_score": 95,
                "swing_signal": "BUY",
                "scalp_signal": "BUY",
                "scalp_confirmed_reversal": True,
            },
        ),
        (
            "SWING",
            {
                "trade_mode": "SCALP",
                "signal": "BUY",
                "score": 95,
                "scalp_score": 95,
                "scalp_signal": "BUY",
                "swing_signal": "BUY",
            },
        ),
    ],
)
def test_other_lane_score_cannot_complete_requested_lane_context(
    monkeypatch, mode, strategy
):
    runtime = SimpleNamespace(last_entry_diagnostics={})
    store = RecordingStore()
    monkeypatch.setattr(shadow_main, "runtime", runtime)
    monkeypatch.setattr(shadow_main, "_brain_authority_store", store)

    allowed = shadow_main._brain_authority_entry_gate(
        "WRONGLANESCOREUSDT", strategy, mode
    )

    assert allowed is False
    record = store.records[0]
    assert record["trade_mode"] == mode
    assert record["decision_state"] == "REJECTED_INCOMPLETE_CONTEXT"
    assert record["context"]["missing_required_context"] == ["lane_score"]
    assert record["allowed"] is False


@pytest.mark.parametrize("failure_mode", ["false", "exception"])
def test_brain_context_rejection_stays_fail_closed_when_evidence_write_fails(
    monkeypatch, failure_mode
):
    runtime = SimpleNamespace(last_entry_diagnostics={})

    class FailedStore:
        last_error = "OSError: database unreachable"

        def append(self, _record):
            if failure_mode == "exception":
                raise RuntimeError("evidence writer failed")
            return False

    monkeypatch.setattr(shadow_main, "runtime", runtime)
    monkeypatch.setattr(shadow_main, "_brain_authority_store", FailedStore())

    allowed = shadow_main._brain_authority_entry_gate(
        "STOREFAILUSDT", {"signal": "BUY", "score": 95}, "SCALP"
    )

    assert allowed is False
    assert runtime.last_entry_diagnostics["STOREFAILUSDT"]["execution"] == "NOT_RUN"
    persistence_error = runtime.last_entry_diagnostics["__brain_authority__"][
        "persistence_error"
    ]
    assert "unreachable" in persistence_error or "evidence writer failed" in persistence_error


def test_incomplete_brain_context_stops_entry_before_paper_execution(monkeypatch):
    symbol = "NOEXECONINCOMPLETEUSDT"
    runtime = SimpleNamespace(last_entry_diagnostics={})
    store = RecordingStore()
    monkeypatch.setattr(shadow_main, "runtime", runtime)
    monkeypatch.setattr(shadow_main, "_brain_authority_store", store)
    monkeypatch.setitem(
        shadow_main._legacy.latest_scores,
        symbol,
        {"signal": "BUY", "score": 95},
    )
    monkeypatch.setattr(
        shadow_main, "entry_execution_freshness_allowed", lambda *_args: True
    )
    monkeypatch.setattr(shadow_main, "_ticker_cache_stale_active", False)
    monkeypatch.setattr(shadow_main, "_ticker_stale_symbols", set())
    monkeypatch.setattr(shadow_main, "_loss_cooldown", lambda _symbol: 0.0)

    def forbidden_open(*_args, **_kwargs):
        pytest.fail("Paper position opener must not run after Brain rejects context")

    def forbidden_economics(**_kwargs):
        pytest.fail("Entry economics must not run after Brain rejects context")

    monkeypatch.setattr(shadow_main, "_original_runtime_open_position", forbidden_open)
    monkeypatch.setattr(shadow_main, "paper_entry_economics", forbidden_economics)

    position = shadow_main._open_one_position(symbol, 1.0, 0.99, "SCALP")

    assert position is None
    trace = runtime.last_entry_diagnostics[symbol]
    assert trace["result"] == "REJECTED_BRAIN_AUTHORITY"
    assert trace["execution"] == "NOT_RUN"
    assert trace["entry_decision_chain"]["brain_authority"]["allowed"] is False
    assert trace["entry_decision_chain"]["final"]["execution_attempted"] is False
    assert trace["entry_decision_chain"]["final"]["failed_gate"] == (
        "BRAIN_CONTEXT_INCOMPLETE"
    )
    assert len(store.records) == 1
