"""Part 6 compatibility boundary.

The original Part-6 source was a large risk/sizing module.  Its public concepts
are consolidated here while the canonical implementation remains in ``risk.py``.
No new trading rules are introduced in this file.
"""
from __future__ import annotations

from .risk import (
    RiskConfig,
    LossStatistics,
    LossTracker,
    DailyRiskManager,
    WeeklyRiskManager,
    MonthlyRiskManager,
    RiskLockState,
    RiskLockManager,
    RiskManager,
)

__all__ = [
    "RiskConfig",
    "LossStatistics",
    "LossTracker",
    "DailyRiskManager",
    "WeeklyRiskManager",
    "MonthlyRiskManager",
    "RiskLockState",
    "RiskLockManager",
    "RiskManager",
]
