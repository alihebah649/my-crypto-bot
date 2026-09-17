"""Structure-derived target and reward/risk calculator for Entry v2.

Targets come only from closed-candle pivot highs in the lane's allowed
 timeframes. The module is descriptive and deterministic: it never executes
orders and it never changes the Legacy strategy.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence


LANE_TIMEFRAMES: dict[str, tuple[str, ...]] = {
    "SCALP": ("5m", "15m"),
    "SWING": ("15m", "1h", "4h"),
}

MIN_REWARD_RISK: dict[str, float] = {"SCALP": 1.0, "SWING": 1.5}
PIVOT_LEFT = 1
PIVOT_RIGHT = 1
WINDOW_LIMITS: dict[tuple[str, str], int] = {
    ("SCALP", "5m"): 48,
    ("SCALP", "15m"): 24,
    ("SWING", "15m"): 48,
    ("SWING", "1h"): 48,
    ("SWING", "4h"): 30,
}


@dataclass(frozen=True)
class TargetCandidate:
    timeframe: str
    price: float
    source: str
    candle_index: int


@dataclass(frozen=True)
class TargetRRDecision:
    status: str
    trade_mode: str
    entry_price: float
    stop_loss: float
    target_price: float | None
    reward_risk: float | None
    risk_amount: float
    reward_amount: float
    minimum_reward_risk: float
    target_source: str | None
    candidates: tuple[TargetCandidate, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "trade_mode": self.trade_mode,
            "entry_price": self.entry_price,
            "stop_loss": self.stop_loss,
            "target_price": self.target_price,
            "reward_risk": self.reward_risk,
            "risk_amount": self.risk_amount,
            "reward_amount": self.reward_amount,
            "minimum_reward_risk": self.minimum_reward_risk,
            "target_source": self.target_source,
            "candidates": [
                {
                    "timeframe": item.timeframe,
                    "price": item.price,
                    "source": item.source,
                    "candle_index": item.candle_index,
                }
                for item in self.candidates
            ],
        }


def _closed(candles: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    values = list(candles or [])
    return values[:-1] if len(values) > 1 else []


def _pivot_highs(candles: Sequence[Mapping[str, Any]], limit: int) -> list[tuple[float, int]]:
    closed = _closed(candles)
    if len(closed) < (PIVOT_LEFT + PIVOT_RIGHT + 1):
        return []
    window = closed[-limit:]
    pivots: list[tuple[float, int]] = []
    for index in range(PIVOT_LEFT, len(window) - PIVOT_RIGHT):
        try:
            high = float(window[index]["high"])
            left = [float(window[index - offset]["high"]) for offset in range(1, PIVOT_LEFT + 1)]
            right = [float(window[index + offset]["high"]) for offset in range(1, PIVOT_RIGHT + 1)]
        except (KeyError, TypeError, ValueError):
            continue
        if high > max(left) and high >= max(right):
            pivots.append((high, index))
    return pivots


def calculate_target_rr(
    *,
    trade_mode: str,
    entry_price: float,
    stop_loss: float,
    candles_by_timeframe: Mapping[str, Sequence[Mapping[str, Any]]],
) -> TargetRRDecision:
    """Choose the nearest closed pivot-high that satisfies the lane RR floor."""
    mode = str(trade_mode or "").upper()
    minimum_rr = MIN_REWARD_RISK.get(mode)
    if minimum_rr is None:
        return TargetRRDecision("INVALID_TRADE_MODE", mode, float(entry_price), float(stop_loss), None, None, 0.0, 0.0, 0.0, None)

    entry = float(entry_price or 0.0)
    stop = float(stop_loss or 0.0)
    risk = entry - stop
    if entry <= 0 or stop <= 0 or risk <= 0:
        return TargetRRDecision("INVALID_RISK_INPUT", mode, entry, stop, None, None, risk, 0.0, minimum_rr, None)

    candidates: list[TargetCandidate] = []
    for timeframe in LANE_TIMEFRAMES[mode]:
        pivots = _pivot_highs(candles_by_timeframe.get(timeframe, ()), WINDOW_LIMITS[(mode, timeframe)])
        for price, index in pivots:
            if price <= entry:
                continue
            candidates.append(TargetCandidate(
                timeframe=timeframe,
                price=price,
                source=f"{timeframe}_PIVOT_HIGH",
                candle_index=index,
            ))

    candidates = sorted(candidates, key=lambda item: (item.price, item.timeframe))
    if not candidates:
        return TargetRRDecision("NO_TARGET_ABOVE_ENTRY", mode, entry, stop, None, None, risk, 0.0, minimum_rr, None, ())

    for candidate in candidates:
        reward = candidate.price - entry
        rr = reward / risk
        if rr >= minimum_rr:
            return TargetRRDecision(
                "VALID",
                mode,
                entry,
                stop,
                candidate.price,
                rr,
                risk,
                reward,
                minimum_rr,
                candidate.source,
                tuple(candidates),
            )

    nearest = candidates[0]
    reward = nearest.price - entry
    rr = reward / risk
    return TargetRRDecision(
        "NO_TARGET_MEETS_RR",
        mode,
        entry,
        stop,
        None,
        rr,
        risk,
        reward,
        minimum_rr,
        None,
        tuple(candidates),
    )


__all__ = ["TargetCandidate", "TargetRRDecision", "calculate_target_rr"]
