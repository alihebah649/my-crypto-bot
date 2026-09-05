from __future__ import annotations

from unittest.mock import patch

import shadow_main


def test_expanded_universe_contains_only_expected_new_spot_symbols():
    expected = {"XRPUSDT", "XLMUSDT", "HBARUSDT", "SUIUSDT", "BCHUSDT", "TRXUSDT"}
    assert expected.issubset(set(shadow_main.TRADING_SYMBOLS))
    assert len(shadow_main.TRADING_SYMBOLS) == 22


def test_universe_expansion_does_not_change_strategy_thresholds():
    assert shadow_main.SCALP_SCORE_THRESHOLD == 65
    assert shadow_main.SWING_SCORE_THRESHOLD == 80


def test_successful_fill_diagnostic_overrides_stale_rejection():
    symbol = "XRPUSDT"
    trace = {
        "symbol": symbol,
        "result": "REJECTED_EXISTING_POSITION",
        "execution": "FILLED",
        "execution_outcome": "FILLED",
        "position_id": "POS-test-xrp",
    }
    position = type("PositionStub", (), {"symbol": symbol, "status": type("Status", (), {"name": "OPEN"})()})()

    with patch.object(shadow_main.runtime.repository, "get_open_positions", return_value=[position]), \
         patch.dict(shadow_main.runtime.last_entry_diagnostics, {symbol: trace}, clear=True):
        shadow_main._sanitize_entry_diagnostics()

    assert trace["result"] == "POSITION_COMMITTED"
    assert trace["diagnostic_consistency"] == "CONSISTENT"
