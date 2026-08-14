"""Trade Manager Part 1: lifecycle/state models.
Canonical implementation is in trade_manager.models; this file is the stable Part-1 boundary.
"""
from .models import TradeManagerConfig, ManagedPosition, TradeContext, TradeStatistics, ExitReason
__all__ = ["TradeManagerConfig", "ManagedPosition", "TradeContext", "TradeStatistics", "ExitReason"]
