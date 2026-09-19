"""Market-regime normalization for the Brain decision layer.

This module is diagnostic/policy input only. It consumes the strategy's existing
MTF snapshot and never mutates strategy, risk, position, or execution state.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class BrainMarketRegime:
    regime: str
    strength: float
    reason: str
    higher_timeframe_bearish: bool
    higher_timeframe_bullish: bool
    local_reversal: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "regime": self.regime,
            "strength": self.strength,
            "reason": self.reason,
            "higher_timeframe_bearish": self.higher_timeframe_bearish,
            "higher_timeframe_bullish": self.higher_timeframe_bullish,
            "local_reversal": self.local_reversal,
        }


def _norm(value: Any) -> str:
    return str(value or "").upper()


def derive_market_regime(strategy: Mapping[str, Any], *, btc_crashing: bool = False) -> BrainMarketRegime:
    """Derive a conservative regime from already captured MTF strategy facts.

    The hierarchy deliberately prefers explicit higher-timeframe evidence, then
    falls back to the weighted MTF balance already produced by the strategy.
    """
    tf = strategy.get("mtf_timeframe_bias")
    timeframe_bias = dict(tf) if isinstance(tf, Mapping) else {}

    one_h = _norm(timeframe_bias.get("1h"))
    four_h = _norm(timeframe_bias.get("4h"))

    explicit_bear = bool(strategy.get("mtf_higher_timeframes_bearish", False))
    explicit_bull = bool(strategy.get("mtf_higher_timeframes_bullish", False))

    higher_bearish = explicit_bear or (one_h == "BEARISH" and four_h == "BEARISH")
    higher_bullish = explicit_bull or (one_h == "BULLISH" and four_h == "BULLISH")

    local_reversal = bool(
        strategy.get("scalp_confirmed_reversal", False)
        or strategy.get("scalp_high_confidence_recovery", False)
    )

    if btc_crashing:
        return BrainMarketRegime(
            regime="BEAR",
            strength=100.0,
            reason="BTC_CRASH_GUARD",
            higher_timeframe_bearish=higher_bearish,
            higher_timeframe_bullish=higher_bullish,
            local_reversal=local_reversal,
        )

    if higher_bearish:
        return BrainMarketRegime(
            regime="BEAR",
            strength=100.0,
            reason="HIGHER_TIMEFRAME_BEARISH",
            higher_timeframe_bearish=True,
            higher_timeframe_bullish=higher_bullish,
            local_reversal=local_reversal,
        )

    if higher_bullish:
        return BrainMarketRegime(
            regime="BULL",
            strength=100.0,
            reason="HIGHER_TIMEFRAME_BULLISH",
            higher_timeframe_bearish=higher_bearish,
            higher_timeframe_bullish=True,
            local_reversal=local_reversal,
        )

    bull = float(strategy.get("mtf_weighted_bull", 0.0) or 0.0)
    bear = float(strategy.get("mtf_weighted_bear", 0.0) or 0.0)
    net = float(strategy.get("mtf_net", bull - bear) or 0.0)

    if net > 0:
        regime = "BULL"
    elif net < 0:
        regime = "BEAR"
    else:
        regime = "TRANSITION"

    return BrainMarketRegime(
        regime=regime,
        strength=min(100.0, abs(net)),
        reason="MTF_WEIGHTED_BALANCE",
        higher_timeframe_bearish=higher_bearish,
        higher_timeframe_bullish=higher_bullish,
        local_reversal=local_reversal,
    )


__all__ = ["BrainMarketRegime", "derive_market_regime"]
