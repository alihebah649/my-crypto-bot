from __future__ import annotations

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


def test_paper_diagnostics_preserves_fields_without_running_historical_report(monkeypatch):
    _install_diagnostic_fixtures(monkeypatch)
    calls = []

    def unexpected_report_call():
        calls.append(True)
        raise AssertionError("diagnostics must not run the historical aggregate")

    monkeypatch.setattr(module, "_safe_paper_shadow_evidence_report_payload", unexpected_report_call)

    payload, status = _call_diagnostics()

    assert status == 200
    assert calls == []
    assert payload["shadow_evidence_report"]["available"] is False
    assert payload["shadow_evidence_report"]["reason"] == "NOT_EMBEDDED_TO_KEEP_DIAGNOSTICS_FAST"
    assert payload["shadow_evidence_report"]["endpoint"] == "/paper/shadow-evidence-report"
    assert payload["shadow_evidence_report_endpoint"] == "/paper/shadow-evidence-report"
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


def test_historical_report_failure_cannot_break_core_paper_diagnostics(monkeypatch):
    _install_diagnostic_fixtures(monkeypatch)

    def unexpected_report_call():
        raise RuntimeError("test capture failure")

    monkeypatch.setattr(module, "_safe_paper_shadow_evidence_report_payload", unexpected_report_call)
    payload, status = _call_diagnostics()

    assert status == 200
    assert payload["shadow_evidence_report"]["reason"] == "NOT_EMBEDDED_TO_KEEP_DIAGNOSTICS_FAST"
    assert payload["mode"] == "PAPER"
    assert payload["data_count"] == 1
    assert payload["market_data_guard"] == {"state": "READY"}
    assert payload["entry_diagnostics"] == {"BTCUSDT": {"entry_v2_shadow_by_mode": {}}}


def test_report_payload_is_available_at_separate_endpoint_even_when_not_embedded(monkeypatch):
    _install_diagnostic_fixtures(monkeypatch)
    payload, status = _call_diagnostics()

    assert status == 200
    assert payload["shadow_evidence_report"]["available"] is False
    assert payload["shadow_evidence_report"]["reason"] == "NOT_EMBEDDED_TO_KEEP_DIAGNOSTICS_FAST"
    assert payload["shadow_evidence_report_endpoint"] == "/paper/shadow-evidence-report"
    assert payload["mode"] == "PAPER"
