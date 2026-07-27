from dataclasses import dataclass, field
from typing import Dict, Optional
from datetime import datetime, timezone

from core.trade_ledger import TradeLedger


@dataclass
class Position:
    """
    يمثل صفقة مفتوحة داخل المحفظة.
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

    entry_time: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


@dataclass
class PortfolioState:
    """
    يمثل الحالة الكاملة للمحفظة.
    """

    balance: float

    ledger: TradeLedger = field(default_factory=TradeLedger)

    open_positions: Dict[str, Position] = field(default_factory=dict)


class PortfolioEngine:
    """
    محرك إدارة المحفظة.
    """

    def __init__(self, initial_balance: float):

        self.state = PortfolioState(balance=initial_balance)

    # ==========================================================
    # معلومات المحفظة
    # ==========================================================

    @property
    def balance(self) -> float:
        """
        الرصيد النقدي الحالي.
        """
        return self.state.balance

    def get_balance(self) -> float:
        return self.state.balance

    def get_equity(self, current_prices=None) -> float:
        """
        إجمالي قيمة المحفظة = الرصيد + قيمة الصفقات المفتوحة.
        """

        equity = self.state.balance

        for position in self.state.open_positions.values():

            price = position.entry_price

            if current_prices is not None:
                price = current_prices.get(
                    position.symbol,
                    position.entry_price,
                )

            equity += position.quantity * price

        return equity

    def current_exposure(self) -> float:

        exposure = 0.0

        for position in self.state.open_positions.values():

            exposure += (
                position.quantity
                * position.entry_price
            )

        return exposure

    def get_total_exposure(self) -> float:
        return self.current_exposure()

    def open_positions_count(self) -> int:
        return len(self.state.open_positions)

    # ==========================================================
    # إدارة المراكز
    # ==========================================================

    def has_position(self, symbol: str) -> bool:

        position = self.state.open_positions.get(symbol)

        return position is not None and position.is_open

    def get_position(self, symbol: str) -> Optional[Position]:

        return self.state.open_positions.get(symbol)

    def open_position(
        self,
        symbol: str,
        quantity: float,
        entry_price: float,
        atr_stop: float = 0.0,
    ):

        if self.has_position(symbol):
            raise ValueError(
                f"يوجد مركز مفتوح مسبقاً على {symbol}"
            )

        cost = quantity * entry_price

        if cost > self.state.balance:
            raise ValueError("الرصيد غير كافٍ")

        self.state.balance -= cost

        self.state.open_positions[symbol] = Position(
            symbol=symbol,
            quantity=quantity,
            entry_price=entry_price,
            highest_price=entry_price,
            is_open=True,
            atr_stop=atr_stop,
            entry_time=datetime.now(timezone.utc),
        )

        return True

    def update_highest_price(
        self,
        symbol: str,
        current_price: float,
    ):

        position = self.get_position(symbol)

        if position is None:
            return

        if current_price > position.highest_price:
            position.highest_price = current_price

    def close_position(
        self,
        symbol: str,
        exit_price: float,
        fees: float = 0.0,
        exit_reason: str = "UNKNOWN",
        strategy_version: str = "DEV",
        run_id: str = "LOCAL",
    ):

        position = self.get_position(symbol)

        if position is None:
            return None

        gross_profit = (
            (exit_price - position.entry_price)
            * position.quantity
        )

        net_profit = gross_profit - fees

        proceeds = (
            position.quantity * exit_price
        ) - fees

        self.state.balance += proceeds

        self.state.ledger.add_trade(
            symbol=symbol,
            entry_time=position.entry_time,
            exit_time=datetime.now(timezone.utc),
            entry_price=position.entry_price,
            exit_price=exit_price,
            quantity=position.quantity,
            gross_profit=gross_profit,
            fees=fees,
            net_profit=net_profit,
            exit_reason=exit_reason,
            strategy_version=strategy_version,
            run_id=run_id,
        )

        del self.state.open_positions[symbol]

        return net_profit

    # ==========================================================
    # التقارير
    # ==========================================================

    def portfolio_snapshot(self):

        return {
            "balance": self.balance,
            "equity": self.get_equity(),
            "open_positions": list(
                self.state.open_positions.keys()
            ),
            "open_positions_count": self.open_positions_count(),
            "exposure": self.current_exposure(),
            "closed_trades": self.state.ledger.total_trades(),
            "net_profit": self.state.ledger.total_net_profit(),
        }
