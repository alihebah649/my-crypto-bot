"""Contracts for the bot's decision-making Brain layer.

The Brain is an orchestration/advisory layer. It does not execute orders and
cannot bypass risk, exit-policy, or execution boundaries.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, Optional


class BrainAction(str, Enum):
    HOLD = "HOLD"
    ENTER = "ENTER"
    EXIT = "EXIT"
    REVIEW = "REVIEW"
    BLOCK = "BLOCK"


@dataclass(frozen=True, slots=True)
class BrainPosition:
    symbol: str
    trade_mode: str = "SWING"
    pnl_percent: float = 0.0
    age_minutes: float = 0.0
    exit_candidate: bool = False
    hard_stop: bool = False
    timeout: bool = False
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class BrainMarketState:
    symbol: str
    signal: str = "HOLD"
    score: float = 0.0
    scalp_score: float = 0.0
    swing_score: float = 0.0
    regime: str = "UNKNOWN"
    volatility: str = "UNKNOWN"
    macro_support: bool = False
    confirmed_reversal: bool = False
    volume_ratio_5m: float = 0.0
    rsi_5m: Optional[float] = None
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class BrainRiskState:
    locked: bool = False
    lock_reason: str = ""
    daily_pnl: float = 0.0
    open_positions: int = 0
    max_open_positions: int = 0
    free_balance: float = 0.0
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class BrainDecision:
    action: BrainAction
    symbol: str
    confidence: float
    reason: str
    hard_constraint: bool = False
    source: str = "deterministic_brain"
    metadata: Mapping[str, object] = field(default_factory=dict)

    @property
    def executable(self) -> bool:
        """Whether the decision is a candidate for downstream policy/risk review."""
        return self.action in {BrainAction.ENTER, BrainAction.EXIT}
