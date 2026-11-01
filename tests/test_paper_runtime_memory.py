from __future__ import annotations

import os

from core.paper_runtime_memory import build_paper_runtime_memory_snapshot


class _Repository:
    def status_counts(self):
        return {"OPEN": 2, "CLOSED": 7, "FAILED": 1}

    def get_all(self):
        raise AssertionError("diagnostics must not materialize position history")


class _Adapter:
    def __init__(self):
        self.orders = {f"order-{index}": object() for index in range(25)}


class _Runtime:
    def __init__(self):
        self.repository = _Repository()
        self.execution_adapter = _Adapter()
        self.last_entry_diagnostics = {"BTCUSDT": {}, "ETHUSDT": {}}


def test_snapshot_reports_counts_without_copying_repository_or_order_contents(tmp_path, monkeypatch):
    statm = tmp_path / "statm"
    statm.write_text("1000 321 0 0 0 0 0", encoding="ascii")
    monkeypatch.setattr(os, "sysconf", lambda name: 4096)

    payload = build_paper_runtime_memory_snapshot(_Runtime(), statm_path=str(statm))

    assert payload["available"] is True
    assert payload["mode"] == "PAPER_ONLY"
    assert payload["process"]["resident_memory_bytes"] == 321 * 4096
    assert payload["process"]["resident_memory_source"] == "PROC_SELF_STATM"
    assert payload["repository"] == {
        "position_count": 10,
        "status_counts": {"OPEN": 2, "CLOSED": 7, "FAILED": 1},
    }
    assert payload["paper_execution"]["stored_order_results"] == 25
    assert payload["runtime"]["entry_diagnostic_symbols"] == 2


def test_snapshot_gracefully_handles_unavailable_procfs_and_optional_collections(tmp_path):
    class MinimalRuntime:
        repository = None
        execution_adapter = None
        last_entry_diagnostics = None

    payload = build_paper_runtime_memory_snapshot(
        MinimalRuntime(),
        statm_path=str(tmp_path / "missing-statm"),
    )

    assert payload["process"]["resident_memory_bytes"] is None
    assert payload["process"]["resident_memory_source"] == "UNAVAILABLE"
    assert payload["repository"]["position_count"] == 0
    assert payload["paper_execution"]["stored_order_results"] is None
    assert payload["runtime"]["entry_diagnostic_symbols"] is None
