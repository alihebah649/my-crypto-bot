"""Trade Manager Part 3: state mutation boundary.
TradeManager owns active/closed state and exposes atomic lifecycle operations.
"""
from .manager import TradeManager, CloseResult
__all__ = ["TradeManager", "CloseResult"]
