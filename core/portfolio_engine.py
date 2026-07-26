from dataclasses import dataclass, field
from typing import Dict


@dataclass
class Position:
    """
    يمثل صفقة واحدة مفتوحة على أصل مالي واحد.
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
    جميع عمليات فتح وإغلاق الصفقات تمر عبر هذا الكلاس.
    """

    balance: float
    open_positions: Dict[str, Position] = field(default_factory=dict)

    def open_position(self, symbol: str, quantity: float, entry_price: float) -> bool:
        """
        فتح صفقة جديدة.

        Returns
        -------
        True
            إذا تم فتح الصفقة بنجاح.

        False
            إذا كانت هناك صفقة مفتوحة بالفعل على نفس الرمز.
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
