from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import List
import uuid


@dataclass
class TradeRecord:
    """
    يمثل صفقة مغلقة كاملة.
    """

    trade_id: str

    symbol: str

    entry_time: datetime
    exit_time: datetime

    entry_price: float
    exit_price: float

    quantity: float

    gross_profit: float
    fees: float
    net_profit: float

    exit_reason: str

    strategy_version: str

    run_id: str


class TradeLedger:
    """
    دفتر الأستاذ لجميع الصفقات المغلقة.
    """

    def __init__(self):
        self.closed_trades: List[TradeRecord] = []

    def add_trade(
        self,
        symbol: str,
        entry_time: datetime,
        exit_time: datetime,
        entry_price: float,
        exit_price: float,
        quantity: float,
        gross_profit: float,
        fees: float,
        net_profit: float,
        exit_reason: str,
        strategy_version: str,
        run_id: str
    ):

        record = TradeRecord(
            trade_id=uuid.uuid4().hex,

            symbol=symbol,

            entry_time=entry_time,
            exit_time=exit_time,

            entry_price=entry_price,
            exit_price=exit_price,

            quantity=quantity,

            gross_profit=gross_profit,
            fees=fees,
            net_profit=net_profit,

            exit_reason=exit_reason,

            strategy_version=strategy_version,

            run_id=run_id
        )

        self.closed_trades.append(record)

        return record

    def total_trades(self):

        return len(self.closed_trades)

    def total_net_profit(self):

        return sum(t.net_profit for t in self.closed_trades)

    def winning_trades(self):

        return sum(1 for t in self.closed_trades if t.net_profit > 0)

    def losing_trades(self):

        return sum(1 for t in self.closed_trades if t.net_profit <= 0)

    def export(self):

        return [asdict(t) for t in self.closed_trades]
