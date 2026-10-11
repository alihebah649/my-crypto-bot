from __future__ import annotations

from types import SimpleNamespace

import shadow_main_base as module


def _install_diagnostic_fixtures(monkeypatch):
    monkeypatch.setattr(
        module._legacy,
        "latest_scores",
        {"BTCUSDT": {"score": 77, "signal": "BUY", "trade_mode": "SCALP"}},
        raising=False,
    )
    monkeypatch.setattr(module, "TRADING_SYMBOLS", ["BTCUSDT"], raising=False)
    monkeypatch.setattr(module._legacy, "last_score_diagnostics", {}, raising=False)
    monkeypatch.setattr(module, "_market_data_guard_snapshot", lambda: {"state": "READY"})
    monkeypatch.setattr(
        module.runtime,
        "last_entry_diagnostics",
        {"BTCUSDT": {"entry_v2_shadow_by_mode": {}}},
    )


def _call_diagnostics():
    with module.app.test_request_context("/paper/diagnostics"):
        response, status = module._diagnostics()
        return response.get_json(), status


def test_paper_diagnostics_includes_structural_stop_shadow_and_preserves_existing_fields(monkeypatch):
    _install_diagnostic_fixtures(monkeypatch)
    report = {
        "available": True,
        "mode": "PAPER",
        "venue_mode": "MIXED",
        "shadow_only": True,
        "structural_stop_shadow": {
            "shadow_only": True,
            "capture_coverage": {"observed_captures": 4},
        },
    }
    monkeypatch.setattr(module, "_safe_paper_shadow_evidence_report_payload", lambda: report)

    payload, status = _call_diagnostics()

    assert status == 200
    assert payload["shadow_evidence_report"]["structural_stop_shadow"]["capture_coverage"] == {
        "observed_captures": 4,
    }
    assert payload["shadow_evidence_report"]["shadow_only"] is True
    assert {
        "mode",
        "symbol_count",
        "data_count",
        "buy_count",
        "score_threshold",
        "scalp_score_threshold",
        "swing_score_threshold",
        "symbols_added",
        "scores",
        "score_errors",
        "market_data_guard",
        "entry_diagnostics",
    }.issubset(payload)
    assert payload["buy_count"] == 1
    assert payload["scalp_score_threshold"] == 65
    assert payload["swing_score_threshold"] == 80


def test_shadow_report_failure_does_not_break_paper_diagnostics(monkeypatch):
    _install_diagnostic_fixtures(monkeypatch)
    capture = SimpleNamespace(
        historical_analysis=lambda: (_ for _ in ()).throw(RuntimeError("test capture failure"))
    )
    monkeypatch.setattr(module, "_entry_v2_runtime_capture", capture, raising=False)
    monkeypatch.setattr(
        module,
        "_build_entry_v2_shadow_report_endpoint_payload",
        lambda analysis, venue_mode: {"available": True},
        raising=False,
    )

    payload, status = _call_diagnostics()

    assert status == 200
    report = payload["shadow_evidence_report"]
    assert report["available"] is False
    assert report["reason"] == "REPORT_GENERATION_FAILED"
    assert payload["mode"] == "PAPER"
    assert payload["data_count"] == 1
    assert payload["market_data_guard"] == {"state": "READY"}
    assert payload["entry_diagnostics"] == {"BTCUSDT": {"entry_v2_shadow_by_mode": {}}}


def test_missing_shadow_report_builder_is_explicit_and_safe(monkeypatch):
    _install_diagnostic_fixtures(monkeypatch)
    monkeypatch.setattr(module, "_entry_v2_runtime_capture", None, raising=False)
    monkeypatch.setattr(module, "_build_entry_v2_shadow_report_endpoint_payload", None, raising=False)

    payload, status = _call_diagnostics()

    assert status == 200
    assert payload["shadow_evidence_report"]["available"] is False
    assert payload["shadow_evidence_report"]["reason"] == "REPORT_BUILDER_UNAVAILABLE"
    assert payload["mode"] == "PAPER"
