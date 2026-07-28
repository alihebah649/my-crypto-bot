from dataclasses import asdict
from datetime import datetime
from typing import List, Optional
import csv
import json

from core.models import ClosedTrade


class TradeLedger:
    """
    يحتفظ بجميع الصفقات المغلقة
    ويحسب الإحصائيات الأساسية للبوت.
    """

    def __init__(self):

        self.closed_trades: List[ClosedTrade] = []

    # ==========================================================
    # إضافة صفقة
    # ==========================================================

    def add_trade(
        self,
        trade: ClosedTrade,
    ) -> ClosedTrade:

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

        return sum(

            trade.net_profit

            for trade in self.closed_trades

        )

    # ==========================================================
    # إجمالي الرسوم
    # ==========================================================

    def total_fees(self) -> float:

        return sum(

            trade.fees

            for trade in self.closed_trades

        )

    # ==========================================================
    # الصفقات الرابحة
    # ==========================================================

    def winning_trades(self) -> int:

        return sum(

            1

            for trade in self.closed_trades

            if trade.net_profit > 0

        )

    # ==========================================================
    # الصفقات الخاسرة
    # ==========================================================

    def losing_trades(self) -> int:

        return sum(

            1

            for trade in self.closed_trades

            if trade.net_profit <= 0

        )

    # ==========================================================
    # نسبة النجاح
    # ==========================================================

    def win_rate(self) -> float:

        total = self.total_trades()

        if total == 0:

            return 0.0

        return (

            self.winning_trades()

            / total

        ) * 100

    # ==========================================================
    # أكبر ربح
    # ==========================================================

    def largest_win(self) -> float:

        if not self.closed_trades:

            return 0.0

        return max(

            trade.net_profit

            for trade in self.closed_trades

        )

    # ==========================================================
    # أكبر خسارة
    # ==========================================================

    def largest_loss(self) -> float:

        if not self.closed_trades:

            return 0.0

        return min(

            trade.net_profit

            for trade in self.closed_trades

        )    # ==========================================================
    # متوسط الربح
    # ==========================================================

    def average_win(self) -> float:

        wins = [

            trade.net_profit

            for trade in self.closed_trades

            if trade.net_profit > 0

        ]

        if not wins:

            return 0.0

        return sum(wins) / len(wins)

    # ==========================================================
    # متوسط الخسارة
    # ==========================================================

    def average_loss(self) -> float:

        losses = [

            trade.net_profit

            for trade in self.closed_trades

            if trade.net_profit <= 0

        ]

        if not losses:

            return 0.0

        return sum(losses) / len(losses)

    # ==========================================================
    # البحث عن صفقة
    # ==========================================================

    def get_trade(
        self,
        trade_id: str,
    ) -> Optional[ClosedTrade]:

        for trade in self.closed_trades:

            if trade.trade_id == trade_id:

                return trade

        return None

    # ==========================================================
    # تصدير JSON
    # ==========================================================

    def export_json(
        self,
        filename: str,
    ):

        with open(
            filename,
            "w",
            encoding="utf-8",
        ) as f:

            json.dump(

                [

                    asdict(t)

                    for t in self.closed_trades

                ],

                f,

                indent=4,

                default=str,

                ensure_ascii=False,

            )

    # ==========================================================
    # تصدير CSV
    # ==========================================================

    def export_csv(
        self,
        filename: str,
    ):

        if not self.closed_trades:

            return

        with open(

            filename,

            "w",

            newline="",

            encoding="utf-8",

        ) as f:

            writer = csv.DictWriter(

                f,

                fieldnames=list(

                    asdict(

                        self.closed_trades[0]

                    ).keys()

                ),

            )

            writer.writeheader()

            for trade in self.closed_trades:

                writer.writerow(

                    asdict(trade)

                )

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
