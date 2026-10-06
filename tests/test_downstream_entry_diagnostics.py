from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_downstream_entry_result_logs_risk_facade_execution_diagnostics():
    source = (ROOT / "shadow_main.py").read_text(encoding="utf-8")
    assert "DOWNSTREAM ENTRY RESULT %s mode=%s" in source
    assert 'downstream_trace.get("risk_gateway")' in source
    assert 'downstream_trace.get("risk_reason")' in source
    assert 'downstream_trace.get("facade")' in source
    assert 'downstream_trace.get("execution")' in source
    assert 'downstream_trace.get("result")' in source
