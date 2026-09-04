from __future__ import annotations

from core.binance_reconciliation import ReconciliationIssue, ReconciliationResult
from core.startup_reconciliation_gate import StartupReconciliationGate


def test_safe_reconciliation_allows_resume():
    result = ReconciliationResult(safe_to_resume=True, issues=())
    decision = StartupReconciliationGate.evaluate(result)
    assert decision.allowed is True
    assert decision.reason == "RECONCILIATION_SAFE"


def test_any_reconciliation_issue_blocks_resume():
    result = ReconciliationResult(
        safe_to_resume=False,
        issues=(ReconciliationIssue("UNPROTECTED_POSITION", "ADAUSDT", "missing stop"),),
    )
    decision = StartupReconciliationGate.evaluate(result)
    assert decision.allowed is False
    assert decision.reason == "RECONCILIATION_BLOCKED"
