"""Pure policy for assigning paper market-data symbols to venues."""
from __future__ import annotations

from collections.abc import Sequence


def market_data_symbol_groups(
    symbols: Sequence[str],
    venue_mode: str,
    *,
    main_binance_only: bool = False,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Return Binance, Bybit, and OKX symbol groups without mixing candle venues.

    The opt-in main-only override applies exclusively to MIXED (the main bot).
    Isolated venue labs always retain their explicitly selected provider.
    """
    universe = tuple(str(symbol).upper() for symbol in symbols)
    mode = str(venue_mode or "MIXED").strip().upper()

    if mode == "MIXED" and main_binance_only:
        return universe, (), ()
    if mode == "BINANCE_ONLY_LAB":
        return universe, (), ()
    if mode == "BYBIT_ONLY_LAB":
        return (), universe, ()
    if mode == "OKX_ONLY_LAB":
        return (), (), universe

    split = len(universe) // 2
    return universe[:split], universe[split:], ()

def market_data_policy_label(
    venue_mode: str,
    *,
    main_binance_only: bool = False,
) -> str:
    """Describe the active data policy without conflating it with venue mode."""
    mode = str(venue_mode or "MIXED").strip().upper()
    if mode == "MIXED" and main_binance_only:
        return "BINANCE_ONLY_MAIN"
    if mode in {"BINANCE_ONLY_LAB", "BYBIT_ONLY_LAB", "OKX_ONLY_LAB"}:
        return "ISOLATED_VENUE_LAB"
    return "VENUE_SHARDED"

