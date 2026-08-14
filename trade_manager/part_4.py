"""Trade Manager Part 4: protection/execution orchestration boundary."""
from .manager import TradeManager
from .protection import ProtectionLogicEvaluator
from .execution import ExecutionPipeline
__all__ = ["TradeManager", "ProtectionLogicEvaluator", "ExecutionPipeline"]
