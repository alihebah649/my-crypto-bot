"""Modular Trade Manager package.

Parts 1-7 are preserved as explicit modules. Part 8 remains the canonical
spot Position lifecycle boundary. Integration contracts prevent duplicate
Position/execution implementations from silently diverging.
"""
from .models import Position, PositionStatus, PositionSide, PositionCloseReason
from .calculator import PositionCalculator, PositionCalculationResult
from .repository import PositionRepository
from .risk_manager import PositionRiskManager, PositionExitDecision, PositionExitReason
from .controller import PositionController
from .history import PositionHistoryService, PositionHistoryRecord, PositionHistoryRepository
from .metrics import PositionMetrics, PositionMetricsCalculator, PositionMetricsService
from .synchronizer import ExchangePosition, ExchangePositionAdapter, MemoryExchangePositionAdapter, PositionSynchronizer, SynchronizationResult, SynchronizationStatus
from .facade import PositionManagementFacade
from .part1_runtime import RuntimeTradeContext, RuntimeStatistics, TradeManagerRuntime
from .protection_models import Trade, TradeSide, TradeStatus, TradeAction, TradeDecision
from .protection import ProtectionLogicEvaluator
from .part3_state import TradeStateManager
from .part4_monitor import MarketSnapshot, PositionMonitor, PositionMonitorThread
from .part5_exit import ExitReason, ExitResult, ExitValidator, SpotExitService
from .part5_recovery import RecoveryRecord, RecoveryComparisonMatrix, RecoveryReport, RecoveryManager
from .part6_risk import RiskDecision, RiskRejectReason, RiskConfig, RiskController, PositionSizeCalculator, PositionSizeNormalizer, PositionFundingValidator, AdvancedCapitalValidator, RiskLockManager, FinalRiskValidator, FinalRiskDecision
from .part7_execution import OrderSide, OrderType, OrderStatus, ExecutionOrder, ExecutionResultStatus, ExecutionResult, ExecutionError, ExecutionResponse, ExecutionBroker, ExecutionRequestBuilder, ExecutionErrorHandler, BrokerUtilities, TradeManagerExecutionPipeline
from .integration_contracts import CONTRACT, IntegrationContract, RiskSizingRequest, RiskSizingApproval, ExecutionRequest, ExecutionOutcomeRecord, ExecutionOutcome, ExecutionSide
from .core_execution_gateway import CoreExecutionGateway
from .core_position_adapter import core_to_trade_manager, trade_manager_to_core

__all__ = [
    "Position","PositionStatus","PositionSide","PositionCloseReason","PositionCalculator","PositionCalculationResult","PositionRepository",
    "PositionRiskManager","PositionExitDecision","PositionExitReason","PositionController","PositionHistoryService","PositionHistoryRecord","PositionHistoryRepository",
    "PositionMetrics","PositionMetricsCalculator","PositionMetricsService","ExchangePosition","ExchangePositionAdapter","MemoryExchangePositionAdapter","PositionSynchronizer","SynchronizationResult","SynchronizationStatus",
    "PositionManagementFacade","RuntimeTradeContext","RuntimeStatistics","TradeManagerRuntime","Trade","TradeSide","TradeStatus","TradeAction","TradeDecision","ProtectionLogicEvaluator","TradeStateManager",
    "MarketSnapshot","PositionMonitor","PositionMonitorThread","ExitReason","ExitResult","ExitValidator","SpotExitService","RecoveryRecord","RecoveryComparisonMatrix","RecoveryReport","RecoveryManager",
    "RiskDecision","RiskRejectReason","RiskConfig","RiskController","PositionSizeCalculator","PositionSizeNormalizer","PositionFundingValidator","AdvancedCapitalValidator","RiskLockManager","FinalRiskValidator","FinalRiskDecision",
    "OrderSide","OrderType","OrderStatus","ExecutionOrder","ExecutionResultStatus","ExecutionResult","ExecutionError","ExecutionResponse","ExecutionBroker","ExecutionRequestBuilder","ExecutionErrorHandler","BrokerUtilities","TradeManagerExecutionPipeline",
    "CONTRACT","IntegrationContract","RiskSizingRequest","RiskSizingApproval","ExecutionRequest","ExecutionOutcomeRecord","ExecutionOutcome","ExecutionSide","CoreExecutionGateway","core_to_trade_manager","trade_manager_to_core",
]
