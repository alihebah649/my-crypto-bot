"""Venue-safe stream routing for the Paper structural-stop comparison.

This module is pure configuration/lookup. It never touches trading decisions.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


STRUCTURAL_STOP_COMPARISON_VENUES = {
    # MAIN stores its restored watches under the canonical report mode MAIN,
    # while the process itself runs in MIXED mode. Both names must resolve to
    # the same Binance Relay stream so a restart cannot strand those watches.
    "MIXED": ("BINANCE", "_binance_market_stream", "MAIN"),
    "MAIN": ("BINANCE", "_binance_market_stream", "MAIN"),
    "BINANCE_ONLY_LAB": ("BINANCE", "_binance_market_stream", "BINANCE_ONLY_LAB"),
    "BYBIT_ONLY_LAB": ("BYBIT", "_bybit_market_stream", "BYBIT_ONLY_LAB"),
    "OKX_ONLY_LAB": ("OKX", "_okx_market_stream", "OKX_ONLY_LAB"),
}


def resolve_structural_stop_stream(
    venue_mode: str | None,
    default_mode: str | None,
    streams: Mapping[str, Any],
) -> tuple[str, Any | None, str]:
    """Resolve a persisted venue mode to its own stream and canonical report mode."""
    mode = str(venue_mode or default_mode or "UNKNOWN").upper()
    spec = STRUCTURAL_STOP_COMPARISON_VENUES.get(mode)
    if spec is None:
        return "UNKNOWN", None, mode
    venue, stream_name, report_mode = spec
    return venue, streams.get(stream_name), report_mode


__all__ = [
    "STRUCTURAL_STOP_COMPARISON_VENUES",
    "resolve_structural_stop_stream",
]
