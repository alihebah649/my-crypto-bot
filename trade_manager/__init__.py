"""Trade Manager integration package.

Part 8.1-8.8 is the canonical position lifecycle boundary. Parts 1-7 remain
available as compatibility boundaries while the system is migrated to the
canonical Part-8 Position model.
"""
from .models import (
    TradeManagerConfig, ManagedPosition, TradeContext, TradeStatistics,
    ProtectionDecision, ProtectionAction, ExitReason,
    Position, PositionStatus, PositionSide, PositionCloseReason,
)
from .risk import (
    RiskConfig, RiskManager, RiskEvaluation, LossTracker, LossStatistics,
    DailyRiskManager, WeeklyRiskManager, MonthlyRiskManager,
    RiskLockManager, RiskLockState,
)
from .protection import ProtectionLogicEvaluator
from .execution import (
    ExecutionOrder, ExecutionResult, ExecutionPipeline,
    ExecutionStatus, OrderSide, OrderType,
)
from .core_execution_adapter import CoreExecutionBrokerAdapter
from .recovery import RecoveryManager, RecoveryReport
from .manager import TradeManager, CloseResult
from .facade import PositionManagementFacade
from .repository import PositionRepository
from .calculator import PositionCalculator, PositionCalculationResult
from .risk_manager import PositionRiskManager, PositionExitDecision, PositionExitReason
from .core_bridge import CorePositionBridge, from_core_position, apply_to_core_position
from .integration_contract import EntryIntent, EntryResult, INTEGRATION_ORDER
from .integration import TradeManagerIntegration, IntegrationConfig

__all__ = [
    "TradeManagerConfig", "ManagedPosition", "TradeContext", "TradeStatistics",
    "ProtectionDecision", "ProtectionAction", "ExitReason", "RiskConfig",
    "RiskManager", "RiskEvaluation", "LossTracker", "LossStatistics",
    "DailyRiskManager", "WeeklyRiskManager", "MonthlyRiskManager",
    "RiskLockManager", "RiskLockState", "ProtectionLogicEvaluator",
    "ExecutionOrder", "ExecutionResult", "ExecutionPipeline", "ExecutionStatus",
    "OrderSide", "OrderType", "CoreExecutionBrokerAdapter", "RecoveryManager",
    "RecoveryReport", "TradeManager", "CloseResult", "PositionManagementFacade",
    "PositionRepository", "PositionCalculator", "PositionCalculationResult",
    "Position", "PositionStatus", "PositionSide", "PositionCloseReason",
    "PositionRiskManager", "PositionExitDecision", "PositionExitReason",
    "CorePositionBridge", "from_core_position", "apply_to_core_position",
    "EntryIntent", "EntryResult", "INTEGRATION_ORDER",
    "TradeManagerIntegration", "IntegrationConfig",
]

__version__ = "1.4.3-integrated"
