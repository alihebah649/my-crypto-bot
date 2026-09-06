from __future__ import annotations

from types import SimpleNamespace


def test_dual_lane_guard_must_not_allow_duplicate_of_existing_lane(monkeypatch):
    import shadow_main

    existing_scalp = SimpleNamespace(
        symbol="TESTUSDT",
        status=SimpleNamespace(name="OPEN"),
        entry_metadata={"trade_mode": "SCALP"},
    )
    monkeypatch.setattr(
        shadow_main.runtime.repository,
        "get_by_symbol",
        lambda symbol: [existing_scalp],
    )
    shadow_main._legacy.latest_scores["TESTUSDT"] = {
        "scalp_signal": "BUY",
        "swing_signal": "BUY",
    }
    try:
        # The opposite SWING lane is available, but the already-open SCALP
        # lane must remain blocked. The production orchestration must therefore
        # open only SWING in this situation.
        assert shadow_main._lane_aware_has_position("TESTUSDT") is False

        opened_modes = []

        def fake_open(symbol, entry_price, stop_loss, trade_mode):
            opened_modes.append(trade_mode)
            return SimpleNamespace(
                position_id=f"{trade_mode.lower()}-1",
                entry_metadata={"trade_mode": trade_mode},
                metadata={},
            )

        monkeypatch.setattr(shadow_main, "_original_runtime_open_position", fake_open)
        monkeypatch.setattr(shadow_main.runtime.repository, "update", lambda position: None)
        shadow_main._open_position_with_selected_mode("TESTUSDT", 100.0, 98.0)

        assert opened_modes == ["SWING"]
    finally:
        shadow_main._legacy.latest_scores.pop("TESTUSDT", None)
        shadow_main.runtime.last_entry_diagnostics.pop("TESTUSDT", None)
