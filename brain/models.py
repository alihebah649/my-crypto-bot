"""Typed contracts for the trading decision brain.

The brain is advisory/coordinating only. Risk and execution remain authoritative.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional


class BrainAction(str, Enum):
    OPEN = "OPEN"
    HOLD = "HOLD"
    CLOSE = "CLOSE"
    REVIEW = "REVIEW"
    BLOCK = "BLOCK"


@dataclass(frozen=True, slots=True)
class BrainSafetyState:
    risk_locked: bool = False
    hard_exit_required: bool = False
    execution_available: bool = True
    paper_mode: bool = True


@dataclass(frozen=True, slots=True)
class BrainInput:
    symbol: str
    market: Mapping[str, Any] = field(default_factory=dict)
    signal: Mapping[str, Any] = field(default_factory=dict)
    position: Optional[Mapping[str, Any]] = None
    risk: Mapping[str, Any] = field(default_factory=dict)
    portfolio: Mapping[str, Any] = field(default_factory=dict)
    safety: BrainSafetyState = field(default_factory=BrainSafetyState)


@dataclass(frozen=True, slots=True)
class BrainDecision:
    action: BrainAction
    confidence: float
    reason: str
    symbol: str
    mode: str = "NONE"
    allow_exception: bool = False
    exception_type: Optional[str] = None
    constraints: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        if not self.symbol:
            raise ValueError("symbol is required")


__all__ = ["BrainAction", "BrainDecision", "BrainInput", "BrainSafetyState"]
