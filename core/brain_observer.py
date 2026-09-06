"""Shadow-mode coordinator for feeding existing bot state into the Brain."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional

from .brain_engine import TradingBrain
from .brain_models import BrainDecision, BrainMarketState, BrainPosition, BrainRiskState


@dataclass(frozen=True, slots=True)
class BrainObservationBatch:
    decisions: List[BrainDecision]


class BrainObserver:
    """Runs Brain decisions without mutating positions or submitting orders."""

    def __init__(self, brain: Optional[TradingBrain] = None) -> None:
        self.brain = brain or TradingBrain()

    def evaluate(
        self,
        *,
        markets: Iterable[BrainMarketState],
        risk: BrainRiskState,
        positions: Iterable[BrainPosition] = (),
    ) -> BrainObservationBatch:
        by_symbol = {p.symbol.upper(): p for p in positions}
        decisions: List[BrainDecision] = []
        for market in markets:
            position = by_symbol.get(market.symbol.upper())
            decisions.append(self.brain.decide(market=market, risk=risk, position=position))
        return BrainObservationBatch(decisions=decisions)


__all__ = ["BrainObservationBatch", "BrainObserver"]
