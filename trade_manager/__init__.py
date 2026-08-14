"""Modular Trade Manager package.

Part 8 remains the canonical Position lifecycle boundary. Parts 1-5 are
exposed as explicit compatibility/runtime layers rather than merged into a
single conflicting implementation.
"""
from .models import Position, PositionStatus, PositionSide, PositionCloseReason
from .calculator import PositionCalculator, PositionCalculationResult
from .repository import PositionRepository
from .risk_manager import PositionRiskManager, PositionExitDecision, PositionExitReason
from .controller import PositionController
from .history import PositionHistoryService, PositionHistoryRecord, PositionHistoryRepository
from .metrics import PositionMetrics, PositionMetricsCalculator, PositionMetricsService
from .synchronizer import (
    ExchangePosition, ExchangePositionAdapter, MemoryExchangePositionAdapter,
    PositionSynchronizer, SynchronizationResult, SynchronizationStatus,
)
from .facade import PositionManagementFacade
from .part1_runtime import RuntimeTradeContext, RuntimeStatistics, TradeManagerRuntime
from .part3_state import TradeStateManager
from .part4_monitor import MarketSnapshot, PositionMonitor, PositionMonitorThread
from .part5_exit import ExitReason, ExitResult, ExitValidator, SpotExitService
from .part5_recovery import RecoveryRecord, RecoveryComparisonMatrix, RecoveryReport, RecoveryManager

__all__ = [
    "Position", "PositionStatus", "PositionSide", "PositionCloseReason",
    "PositionCalculator", "PositionCalculationResult", "PositionRepository",
    "PositionRiskManager", "PositionExitDecision", "PositionExitReason",
    "PositionController", "PositionHistoryService", "PositionHistoryRecord",
    "PositionHistoryRepository", "PositionMetrics", "PositionMetricsCalculator",
    "PositionMetricsService", "ExchangePosition", "ExchangePositionAdapter",
    "MemoryExchangePositionAdapter", "PositionSynchronizer", "SynchronizationResult",
    "SynchronizationStatus", "PositionManagementFacade", "RuntimeTradeContext",
    "RuntimeStatistics", "TradeManagerRuntime", "TradeStateManager", "MarketSnapshot",
    "PositionMonitor", "PositionMonitorThread", "ExitReason", "ExitResult",
    "ExitValidator", "SpotExitService", "RecoveryRecord", "RecoveryComparisonMatrix",
    "RecoveryReport", "RecoveryManager",
]
