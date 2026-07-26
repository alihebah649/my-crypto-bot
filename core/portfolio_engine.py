from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class Position:
    """
    يمثل صفقة واحدة مفتوحة.
    """

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
    """
    يمثل الحالة الكاملة للمحفظة.
    جميع عمليات إدارة الصفقات تتم من خلال هذا الكلاس.
    """

    balance: float
    open_positions: Dict[str, Position] = field(default_factory=dict)

    # =====================================================
    # إدارة الصفقات
    # =====================================================

    def open_position(
        self,
        symbol: str,
        quantity: float,
        entry_price: float
    ) -> bool:

        if symbol in self.open_positions:
            return False

        self.open_positions[symbol] = Position(
            symbol=symbol,
            quantity=quantity,
            entry_price=entry_price,
            highest_price=entry_price,
            is_open=True
        )

        return True

    def close_position(self, symbol: str) -> bool:

        if symbol not in self.open_positions:
            return False

        del self.open_positions[symbol]
        return True

    # =====================================================
    # الاستعلام
    # =====================================================

    def has_position(self, symbol: str) -> bool:
        return symbol in self.open_positions

    def get_position(self, symbol: str) -> Optional[Position]:
        return self.open_positions.get(symbol)

    def total_open_positions(self) -> int:
        return len(self.open_positions)

    # =====================================================
    # تحديثات الصفقة
    # =====================================================

    def update_highest_price(self, symbol: str, current_price: float):

        position = self.get_position(symbol)

        if position is None:
            return

        if current_price > position.highest_price:
            position.highest_price = current_price

    # =====================================================
    # الحسابات
    # =====================================================

    def unrealized_pnl(self, symbol: str, current_price: float) -> float:

        position = self.get_position(symbol)

        if position is None:
            return 0.0

        return (current_price - position.entry_price) * position.quantity

    def exposure_usd(self) -> float:

        total = 0.0

        for position in self.open_positions.values():
            total += position.entry_price * position.quantity

        return total
