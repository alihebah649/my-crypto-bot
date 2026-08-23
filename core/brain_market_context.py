"""Normalize existing strategy indicators into a read-only Brain market context."""
from __future__ import annotations

from typing import Any, Mapping, Optional


class BrainMarketContextAdapter:
    """Adapter only; it never calculates or mutates strategy state."""

    _KEYS = (
        "ema_100", "ema", "atr", "atr_percent", "bollinger", "bb_upper",
        "bb_middle", "bb_lower", "trend", "volatility", "market_regime",
        "candlestick_pattern", "bullish_pattern", "bearish_pattern", "score",
    )

    @classmethod
    def build(cls, market: Optional[Mapping[str, Any]] = None, strategy: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
        source: dict[str, Any] = {}
        if market:
            source.update(dict(market))
        if strategy:
            source.update(dict(strategy))
        return {key: source[key] for key in cls._KEYS if key in source}


__all__ = ["BrainMarketContextAdapter"]
