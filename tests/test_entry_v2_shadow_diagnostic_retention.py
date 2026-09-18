from __future__ import annotations

from types import SimpleNamespace

from trade_manager.shadow_integration import ShadowTradeManagerRuntime


def test_open_position_preserves_entry_v2_shadow_diagnostic(tmp_path):
    runtime = ShadowTradeManagerRuntime(
        initial_cash=1000.0,
        fee_rate=0.001,
        persistence_dir=str(tmp_path / "paper"),
    )

    shadow = {
        "capture_id": "capture-123",
        "v2_decision": "REJECTED",
        "v2_failed_gate": "STRUCTURAL_RECLAIM_NOT_CONFIRMED",
    }
    runtime.last_entry_diagnostics["TESTUSDT"] = {
        "symbol": "TESTUSDT",
        "entry_v2_shadow": shadow,
        "stale_field": "must_not_be_carried",
    }

    runtime.risk_gateway.approve = lambda request: SimpleNamespace(
        approved=True,
        reason="APPROVED",
        quantity=0.5,
        position_value=50.0,
        capital_required=50.0,
        metadata={"source": "test"},
    )
    runtime.facade.open_position = lambda **kwargs: None
    runtime.facade.last_entry_diagnostic = {
        "execution_gateway": "PASS",
        "execution_outcome": {"success": True},
        "result": "POSITION_COMMITTED",
    }

    runtime.open_position("TESTUSDT", 100.0, 99.0, trade_mode="SCALP")

    trace = runtime.last_entry_diagnostics["TESTUSDT"]
    assert trace["entry_v2_shadow"] == shadow
    assert "stale_field" not in trace


def test_open_position_does_not_invent_entry_v2_shadow_without_candidate(tmp_path):
    runtime = ShadowTradeManagerRuntime(
        initial_cash=1000.0,
        fee_rate=0.001,
        persistence_dir=str(tmp_path / "paper"),
    )

    runtime.risk_gateway.approve = lambda request: SimpleNamespace(
        approved=False,
        reason="MAX_PORTFOLIO_EXPOSURE",
        quantity=0.0,
        position_value=0.0,
        capital_required=0.0,
        metadata={},
    )

    runtime.open_position("TESTUSDT", 100.0, 99.0, trade_mode="SCALP")

    trace = runtime.last_entry_diagnostics["TESTUSDT"]
    assert "entry_v2_shadow" not in trace
