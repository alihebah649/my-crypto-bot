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
    جميع عمليات فتح وإغلاق وإدارة الصفقات تتم من خلال هذا الكلاس.
    """

    balance: float
    open_positions: Dict[str, Position] = field(default_factory=dict)

    # ==========================
    # إدارة الصفقات
    # ==========================

    def open_position(
        self,
        symbol: str,
        quantity: float,
        entry_price: float
    ) -> bool:
        """
        فتح صفقة جديدة.
        """

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
        """
        إغلاق صفقة.
        """

        if symbol not in self.open_positions:
            return False

        del self.open_positions[symbol]
        return True

    # ==========================
    # الاستعلامات
    # ==========================

    def has_position(self, symbol: str) -> bool:
        """
        هل توجد صفقة مفتوحة؟
        """

        return symbol in self.open_positions

    def get_position(self, symbol: str) -> Optional[Position]:
        """
        الحصول على بيانات صفقة.
        """

        return self.open_positions.get(symbol)

    def total_open_positions(self) -> int:
        """
        عدد الصفقات المفتوحة.
        """

        return len(self.open_positions)
