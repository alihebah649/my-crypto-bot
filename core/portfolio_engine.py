from dataclasses import dataclass, field
from typing import Dict


@dataclass
class Position:
    symbol: str
    quantity: float = 0.0
    entry_price: float = 0.0
    highest_price: float = 0.0

    is_open: bool = False
    trailing_active: bool = False
    recovery_mode: bool = False

    atr_stop: float = 0.0
    last_stop_time: float = 0.0
    recovery_start_time: float = 0.0


@dataclass
class PortfolioState:
    balance: float
    open_positions: Dict[str, Position] = field(default_factory=dict)
