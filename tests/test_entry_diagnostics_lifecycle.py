from __future__ import annotations

import shadow_main


def test_entry_diagnostics_are_cycle_scoped(monkeypatch):
    shadow_main.runtime.last_entry_diagnostics.clear()
    shadow_main.runtime.last_entry_diagnostics["OPUSDT"] = {
        "result": "REJECTED_EXISTING_POSITION",
        "execution": "FILLED",
        "position_id": "OLD-POSITION",
    }
    shadow_main.runtime.last_entry_diagnostics["__paper_loop__"] = {"cycle": 9}
    seen = {}

    def fake_market_cycle():
        seen.update(shadow_main.runtime.last_entry_diagnostics)

    monkeypatch.setattr(shadow_main, "_paper_original_process_market_cycle", fake_market_cycle)
    monkeypatch.setattr(shadow_main._entry_v2_runtime_capture, "capture_cycle", lambda: {})
    monkeypatch.setattr(shadow_main, "_last_btc_guard", {"crashing": False, "drop_percent": 0.0})

    shadow_main._process_market_cycle_with_overlays()

    assert "OPUSDT" not in seen
    assert "__paper_loop__" in seen
    shadow_main.runtime.last_entry_diagnostics.clear()


def test_successful_paper_open_replaces_stale_rejection_trace(monkeypatch):
    shadow_main.runtime.last_entry_diagnostics.clear()
    shadow_main.runtime.last_entry_diagnostics["OPUSDT"] = {
        "result": "REJECTED_EXISTING_POSITION",
        "execution": "NOT_RUN",
        "positions_opened": [],
    }

    class FakePosition:
        position_id = "POS-NEW"
        entry_metadata = {"trade_mode": "SCALP"}
        metadata = {"trade_mode": "SCALP"}

    monkeypatch.setattr(shadow_main._legacy, "latest_scores", {
        "OPUSDT": {"scalp_signal": "BUY", "swing_signal": "HOLD"}
    })
    monkeypatch.setattr(shadow_main, "_open_one_position", lambda *args: FakePosition())

    opened = shadow_main._open_position_with_selected_mode("OPUSDT", 0.123, 0.120)
    trace = shadow_main.runtime.last_entry_diagnostics["OPUSDT"]

    assert opened.position_id == "POS-NEW"
    assert trace["result"] == "POSITION_COMMITTED"
    assert trace["execution"] == "FILLED"
    assert trace["position_id"] == "POS-NEW"
    assert trace["positions_opened"] == ["POS-NEW"]
    assert trace["diagnostic_consistency"] == "CONSISTENT"
    shadow_main.runtime.last_entry_diagnostics.clear()
