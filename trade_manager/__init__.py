"""Trade Manager integration package."""
from .models import TradeManagerConfig, ManagedPosition, TradeContext, TradeStatistics, ProtectionDecision, ProtectionAction, ExitReason
from .risk import RiskConfig, RiskManager, RiskEvaluation
from .protection import ProtectionLogicEvaluator
from .execution import ExecutionOrder, ExecutionResult, ExecutionPipeline
from .recovery import RecoveryManager, RecoveryReport
from .manager import TradeManager

__all__ = [
    "TradeManagerConfig", "ManagedPosition", "TradeContext", "TradeStatistics",
    "ProtectionDecision", "ProtectionAction", "ExitReason", "RiskConfig",
    "RiskManager", "RiskEvaluation", "ProtectionLogicEvaluator", "ExecutionOrder",
    "ExecutionResult", "ExecutionPipeline", "RecoveryManager", "RecoveryReport",
    "TradeManager",
]
__version__ = "1.0.0-integrated"
