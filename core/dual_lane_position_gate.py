from __future__ import annotations

from collections.abc import Mapping, Set


_VALID_MODES = {"SCALP", "SWING"}


def requested_trade_modes(strategy: Mapping[str, object]) -> set[str]:
    """Return the lanes that the current strategy observation requests."""
    modes: set[str] = set()
    if str(strategy.get("scalp_signal") or "").upper() == "BUY":
        modes.add("SCALP")
    if str(strategy.get("swing_signal") or "").upper() == "BUY":
        modes.add("SWING")
    if not modes and str(strategy.get("signal") or "").upper() == "BUY":
        mode = str(strategy.get("trade_mode") or "").upper()
        if mode in _VALID_MODES:
            modes.add(mode)
    return modes


def block_for_existing_position(
    strategy: Mapping[str, object],
    active_trade_modes: Set[str],
) -> bool:
    """Block only when every requested lane already has a position."""
    requested = requested_trade_modes(strategy)
    active = {str(mode).upper() for mode in active_trade_modes}
    if not requested:
        return False
    return requested.issubset(active)
