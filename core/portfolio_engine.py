from dataclasses import dataclass, field
from typing import Dict, Optional


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

    # -----------------------------
    # Position Management
    # -----------------------------

    def open_position(
        self,
        symbol: str,
        quantity: float,
        entry_price: float,
        atr_stop: float = 0.0,
    ):

        self.open_positions[symbol] = Position(
            symbol=symbol,
            quantity=quantity,
            entry_price=entry_price,
            highest_price=entry_price,
            is_open=True,
            atr_stop=atr_stop,
        )

    def get_position(self, symbol: str) -> Optional[Position]:
        return self.open_positions.get(symbol)

    def close_position(self, symbol: str):

        if symbol in self.open_positions:
            del self.open_positions[symbol]

    def has_position(self, symbol: str) -> bool:
        return symbol in self.open_positions

    # -----------------------------
    # Portfolio Statistics
    # -----------------------------

    def exposure_usd(self, current_prices: Dict[str, float]) -> float:

        exposure = 0.0

        for symbol, position in self.open_positions.items():

            if symbol not in current_prices:
                continue

            exposure += (
                current_prices[symbol] *
                position.quantity
            )

        return exposure

    def unrealized_pnl(
        self,
        current_prices: Dict[str, float]
    ) -> float:

        pnl = 0.0

        for symbol, position in self.open_positions.items():

            if symbol not in current_prices:
                continue

            pnl += (
                current_prices[symbol]
                - position.entry_price
            ) * position.quantity

        return pnl

    # -----------------------------
    # Trade Settlement
    # -----------------------------

    def realize_position(
        self,
        symbol: str,
        exit_price: float,
        fee_rate: float
    ) -> float:
        """
        إغلاق الصفقة وحساب الربح أو الخسارة الصافية بعد الرسوم.
        """

        position = self.get_position(symbol)

        if position is None:
            return 0.0

        gross_profit = (
            exit_price - position.entry_price
        ) * position.quantity

        fees = (
            (
                position.entry_price * position.quantity
            ) +
            (
                exit_price * position.quantity
            )
        ) * fee_rate

        net_profit = gross_profit - fees

        self.balance += net_profit

        self.close_position(symbol)

        return net_profit
