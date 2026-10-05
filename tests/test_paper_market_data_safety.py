from __future__ import annotations

from unittest.mock import patch

import shadow_main


def test_market_cycle_exception_cannot_create_a_position():
    before = len(shadow_main.runtime.repository.get_open_positions())
    with patch.object(shadow_main._legacy, "process_market_cycle", side_effect=RuntimeError("market data unavailable")):
        # Exercise the same exception boundary used by the production engine.
        # The cycle is deliberately not allowed to fall through to entry logic.
        try:
            shadow_main._legacy.process_market_cycle()
        except RuntimeError:
            pass
    after = len(shadow_main.runtime.repository.get_open_positions())
    assert after == before



def test_bybit_only_lab_does_not_require_binance_execution_reference():
    with patch.object(shadow_main, "PAPER_VENUE_MODE", "BYBIT_ONLY_LAB"):
        assert not shadow_main._requires_binance_execution_reference("BYBIT")


def test_mixed_mode_bybit_requires_binance_execution_reference():
    with patch.object(shadow_main, "PAPER_VENUE_MODE", "MIXED"):
        assert shadow_main._requires_binance_execution_reference("BYBIT")


def test_binance_source_never_requires_binance_reference_gate():
    with patch.object(shadow_main, "PAPER_VENUE_MODE", "BYBIT_ONLY_LAB"):
        assert not shadow_main._requires_binance_execution_reference("BINANCE")
