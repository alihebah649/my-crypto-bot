from dataclasses import asdict, dataclass
from datetime import datetime
from typing import List, Optional
import csv
import json


@dataclass(slots=True)
class ClosedTrade:
    """Canonical closed-trade record consumed by PortfolioEngine and reports."""
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
    strategy_version: str = "1.0"
    run_id: str = "default"


class TradeLedger:
    """
    يحتفظ بجميع الصفقات المغلقة
    ويحسب الإحصائيات الأساسية للبوت.

    The ledger accepts either a ClosedTrade instance or the keyword fields
    used by PortfolioEngine._close_position_unlocked().
    """

    def __init__(self):
        self.closed_trades: List[ClosedTrade] = []

    # ==========================================================
    # إضافة صفقة
    # ==========================================================
    def add_trade(
        self,
        trade: Optional[ClosedTrade] = None,
        **trade_data,
    ) -> ClosedTrade:
        if trade is not None and trade_data:
            raise TypeError("Provide either a ClosedTrade or trade fields, not both")

        if trade is None:
            required = {
                "symbol", "entry_time", "exit_time", "entry_price",
                "exit_price", "quantity", "gross_profit", "fees",
                "net_profit", "exit_reason",
            }
            missing = sorted(required.difference(trade_data))
            if missing:
                raise TypeError(f"Missing closed-trade fields: {', '.join(missing)}")
            trade = ClosedTrade(**trade_data)

        self.closed_trades.append(trade)
        return trade

    # ==========================================================
    # عدد الصفقات
    # ==========================================================
    def total_trades(self) -> int:
        return len(self.closed_trades)

    # ==========================================================
    # إجمالي الربح
    # ==========================================================
    def total_net_profit(self) -> float:
        return sum(trade.net_profit for trade in self.closed_trades)

    # ==========================================================
    # إجمالي الرسوم
    # ==========================================================
    def total_fees(self) -> float:
        return sum(trade.fees for trade in self.closed_trades)

    # ==========================================================
    # الصفقات الرابحة
    # ==========================================================
    def winning_trades(self) -> int:
        return sum(1 for trade in self.closed_trades if trade.net_profit > 0)

    # ==========================================================
    # الصفقات الخاسرة
    # ==========================================================
    def losing_trades(self) -> int:
        return sum(1 for trade in self.closed_trades if trade.net_profit <= 0)

    # ==========================================================
    # نسبة النجاح
    # ==========================================================
    def win_rate(self) -> float:
        total = self.total_trades()
        if total == 0:
            return 0.0
        return (self.winning_trades() / total) * 100

    # ==========================================================
    # أكبر ربح
    # ==========================================================
    def largest_win(self) -> float:
        if not self.closed_trades:
            return 0.0
        return max(trade.net_profit for trade in self.closed_trades)

    # ==========================================================
    # أكبر خسارة
    # ==========================================================
    def largest_loss(self) -> float:
        if not self.closed_trades:
            return 0.0
        return min(trade.net_profit for trade in self.closed_trades)

    # ==========================================================
    # متوسط الربح
    # ==========================================================
    def average_win(self) -> float:
        wins = [trade.net_profit for trade in self.closed_trades if trade.net_profit > 0]
        if not wins:
            return 0.0
        return sum(wins) / len(wins)

    # ==========================================================
    # متوسط الخسارة
    # ==========================================================
    def average_loss(self) -> float:
        losses = [trade.net_profit for trade in self.closed_trades if trade.net_profit <= 0]
        if not losses:
            return 0.0
        return sum(losses) / len(losses)

    # ==========================================================
    # البحث عن صفقة
    # ==========================================================
    def get_trade(self, trade_id: str) -> Optional[ClosedTrade]:
        # ClosedTrade is deliberately identified by its ledger position because
        # the current PortfolioEngine does not pass a separate trade_id.
        for trade in self.closed_trades:
            if getattr(trade, "trade_id", None) == trade_id:
                return trade
        return None

    # ==========================================================
    # تصدير JSON
    # ==========================================================
    def export_json(self, filename: str):
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(
                [asdict(t) for t in self.closed_trades],
                f,
                indent=4,
                default=str,
                ensure_ascii=False,
            )

    # ==========================================================
    # تصدير CSV
    # ==========================================================
    def export_csv(self, filename: str):
        if not self.closed_trades:
            return
        with open(filename, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=list(asdict(self.closed_trades[0]).keys()),
            )
            writer.writeheader()
            for trade in self.closed_trades:
                writer.writerow(asdict(trade))

    # ==========================================================
    # حذف جميع الصفقات
    # ==========================================================
    def clear(self):
        self.closed_trades.clear()

    # ==========================================================
    # آخر صفقة
    # ==========================================================
    def last_trade(self) -> Optional[ClosedTrade]:
        if not self.closed_trades:
            return None
        return self.closed_trades[-1]

    # ==========================================================
    # جميع الصفقات
    # ==========================================================
    def all_trades(self) -> List[ClosedTrade]:
        return self.closed_trades
