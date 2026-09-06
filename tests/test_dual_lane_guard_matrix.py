from __future__ import annotations

from types import SimpleNamespace


def _position(mode: str):
    return SimpleNamespace(
        symbol="TESTUSDT",
        status=SimpleNamespace(name="OPEN"),
        entry_metadata={"trade_mode": mode},
    )


def test_lane_guard_matrix(monkeypatch):
    import shadow_main

    cases = [
        ([], ["SCALP", "SWING"]),
        (["SCALP"], ["SWING"]),
        (["SWING"], ["SCALP"]),
        (["SCALP", "SWING"], []),
    ]

    shadow_main._legacy.latest_scores["TESTUSDT"] = {
        "scalp_signal": "BUY",
        "swing_signal": "BUY",
    }
    monkeypatch.setattr(
        shadow_main.runtime.repository,
        "get_by_symbol",
        lambda symbol: [_position(mode) for mode in cases[0][0]],
    )
    monkeypatch.setattr(shadow_main.runtime.repository, "update", lambda position: None)

    try:
        for existing, expected in cases:
            monkeypatch.setattr(
                shadow_main.runtime.repository,
                "get_by_symbol",
                lambda symbol, existing=existing: [_position(mode) for mode in existing],
            )
            opened = []

            def fake_open(symbol, entry_price, stop_loss, trade_mode):
                opened.append(trade_mode)
                return SimpleNamespace(
                    position_id=f"{trade_mode.lower()}-matrix",
                    entry_metadata={"trade_mode": trade_mode},
                    metadata={},
                )

            monkeypatch.setattr(shadow_main, "_original_runtime_open_position", fake_open)
            shadow_main.runtime.last_entry_diagnostics.pop("TESTUSDT", None)
            shadow_main._open_position_with_selected_mode("TESTUSDT", 100.0, 98.0)
            assert opened == expected
    finally:
        shadow_main._legacy.latest_scores.pop("TESTUSDT", None)
        shadow_main.runtime.last_entry_diagnostics.pop("TESTUSDT", None)
