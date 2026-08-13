"""Modular Trade Manager package.

Part 8 is split by responsibility so each component can be reviewed and tested
independently before integration with the rest of the bot.
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

__all__ = [
    "Position", "PositionStatus", "PositionSide", "PositionCloseReason",
    "PositionCalculator", "PositionCalculationResult", "PositionRepository",
    "PositionRiskManager", "PositionExitDecision", "PositionExitReason",
    "PositionController", "PositionHistoryService", "PositionHistoryRecord",
    "PositionHistoryRepository", "PositionMetrics", "PositionMetricsCalculator",
    "PositionMetricsService", "ExchangePosition", "ExchangePositionAdapter",
    "MemoryExchangePositionAdapter", "PositionSynchronizer", "SynchronizationResult",
    "SynchronizationStatus", "PositionManagementFacade",
]
