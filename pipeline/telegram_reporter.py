"""Telegram notifications and daily paper-trading reporting.

Uses Render environment variables TOKEN and TELEGRAMID. The older
TELEGRAM_TOKEN/TELEGRAM_CHAT_ID names are accepted as compatibility fallbacks.
No secrets are logged.
"""
from __future__ import annotations

import logging
import os
from collections import defaultdict
from datetime import datetime, date
from typing import Iterable
from zoneinfo import ZoneInfo

import requests

logger = logging.getLogger("ShadowTrading.Telegram")


class TelegramReporter:
    def __init__(self, *, timeout: float = 10.0) -> None:
        self.token = os.getenv("TOKEN") or os.getenv("TELEGRAM_TOKEN", "")
        self.chat_id = os.getenv("TELEGRAMID") or os.getenv("TELEGRAM_CHAT_ID", "")
        self.enabled = bool(self.token and self.chat_id and os.getenv("ENABLE_TELEGRAM", "true").lower() not in {"0", "false", "no"})
        self.timeout = timeout
        self._session = requests.Session()

    def send(self, text: str) -> bool:
        if not self.enabled:
            logger.warning("Telegram disabled or credentials missing; message not sent")
            return False
        try:
            response = self._session.post(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                data={"chat_id": self.chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
            if not payload.get("ok"):
                raise RuntimeError(payload.get("description", "Telegram API rejected message"))
            return True
        except Exception:
            logger.exception("Telegram message delivery failed")
            return False

    @staticmethod
    def trade_buy(symbol: str, quantity: float, price: float, notional: float, reason: str) -> str:
        return (
            "🟢 <b>صفقة شراء جديدة</b>\n"
            f"1️⃣ المبلغ المستخدم للشراء: <b>${notional:,.2f}</b>\n"
            f"2️⃣ الكمية: <b>{quantity:.10f}</b>\n"
            f"3️⃣ السعر: <b>${price:,.8f}</b>\n"
            f"4️⃣ اسم العملة: <b>{symbol.replace('USDT', '')}</b>\n"
            f"5️⃣ سبب الشراء: <b>{reason}</b>\n"
            "📄 الوضع: <b>PAPER TRADING</b>"
        )

    @staticmethod
    def trade_sell(symbol: str, quantity: float, price: float, net_pnl: float, reason: str, equity: float) -> str:
        emoji = "🟢" if net_pnl >= 0 else "🔴"
        return (
            f"{emoji} <b>صفقة بيع جديدة</b>\n"
            f"1️⃣ الربح/الخسارة الصافية: <b>${net_pnl:,.2f}</b>\n"
            f"2️⃣ السعر: <b>${price:,.8f}</b>\n"
            f"3️⃣ اسم العملة: <b>{symbol.replace('USDT', '')}</b>\n"
            f"4️⃣ سبب الإغلاق: <b>{reason}</b>\n"
            f"📊 إجمالي المحفظة الحالي: <b>${equity:,.2f}</b>\n"
            "📄 الوضع: <b>PAPER TRADING</b>"
        )

    def daily_report(self, trades: Iterable, report_date: date) -> str:
        grouped = defaultdict(lambda: {"win": 0, "loss": 0, "net": 0.0})
        total_win = total_loss = 0
        total_net = 0.0

        for trade in trades:
            exit_time = getattr(trade, "exit_time", None)
            if not exit_time:
                continue
            if getattr(exit_time, "date", lambda: None)() != report_date:
                continue
            symbol = str(getattr(trade, "symbol", "UNKNOWN")).replace("USDT", "")
            pnl = float(getattr(trade, "net_profit", 0.0) or 0.0)
            if pnl > 0:
                grouped[symbol]["win"] += 1
                total_win += 1
            else:
                grouped[symbol]["loss"] += 1
                total_loss += 1
            grouped[symbol]["net"] += pnl
            total_net += pnl

        lines = [
            "📊 <b>حصاد اليوم الشامل</b>",
            f"📅 التاريخ المنتهي: <b>{report_date.isoformat()}</b>",
            "",
            "<pre>",
            "COIN  | WIN | LOSS | NET (FEES)",
            "-------------------------------",
        ]
        for symbol in sorted(grouped):
            row = grouped[symbol]
            lines.append(f"{symbol:<5} | {row['win']:>3} | {row['loss']:>4} | ${row['net']:>10.2f}")
        lines.extend([
            "-------------------------------",
            f"TOTAL | {total_win:>3} | {total_loss:>4} | ${total_net:>10.2f}",
            "</pre>",
            "📄 <b>Paper Trading — لا توجد أوامر حقيقية</b>",
        ])
        return "\n".join(lines)


class PaperTradeTelegramMonitor:
    """Detects new paper positions/closed trades without altering trade logic."""

    def __init__(self, runner, *, interval: float = 5.0, timezone_name: str = "Asia/Aden") -> None:
        self.runner = runner
        self.interval = interval
        self.tz = ZoneInfo(timezone_name)
        self.reporter = TelegramReporter()
        self._seen_open: set[str] = set()
        self._seen_closed = 0
        self._last_report_date = datetime.now(self.tz).date()
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run_forever(self) -> None:
        while not self._stop:
            try:
                self.poll_once()
            except Exception:
                logger.exception("Telegram monitor cycle failed")
            import time
            time.sleep(self.interval)

    def poll_once(self) -> None:
        portfolio = self.runner.portfolio
        positions = dict(portfolio.positions)
        current_ids = {str(getattr(p, "trade_id", symbol)) for symbol, p in positions.items()}

        for symbol, position in positions.items():
            trade_id = str(getattr(position, "trade_id", symbol))
            if trade_id in self._seen_open:
                continue
            self._seen_open.add(trade_id)
            notional = float(position.entry_price) * float(position.quantity)
            reason = str(getattr(position, "metadata", {}).get("reason", "ENTRY"))
            self.reporter.send(self.reporter.trade_buy(symbol, position.quantity, position.entry_price, notional, reason))

        self._seen_open.intersection_update(current_ids)

        closed_trades = portfolio.trade_ledger.all_trades()
        if len(closed_trades) > self._seen_closed:
            for trade in closed_trades[self._seen_closed:]:
                self.reporter.send(self.reporter.trade_sell(
                    trade.symbol, trade.quantity, trade.exit_price, trade.net_profit,
                    trade.exit_reason, portfolio.total_equity(),
                ))
            self._seen_closed = len(closed_trades)

        now = datetime.now(self.tz)
        if now.date() != self._last_report_date:
            previous_day = self._last_report_date
            if self.reporter.send(self.reporter.daily_report(closed_trades, previous_day)):
                self._last_report_date = now.date()
