"""Part 7 compatibility boundary.

Part 7 owns order/execution semantics.  The actual exchange-independent
implementation is in ``execution.py`` and the bridge to the current core
ExecutionAdapter is ``core_execution_adapter.py``.
"""
from .execution import (
    OrderSide,
    OrderType,
    ExecutionStatus,
    ExecutionOrder,
    ExecutionResult,
    ExecutionBroker,
    ExecutionPipeline,
)
from .core_execution_adapter import CoreExecutionBrokerAdapter

__all__ = [
    "OrderSide",
    "OrderType",
    "ExecutionStatus",
    "ExecutionOrder",
    "ExecutionResult",
    "ExecutionBroker",
    "ExecutionPipeline",
    "CoreExecutionBrokerAdapter",
]
