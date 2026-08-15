"""Canonical entry point for Shadow Trading Bot.

The runtime uses the PaperTradingRunner with Trade Manager as the canonical
Part-6/7/8 boundary. The legacy bot.py entry point is intentionally not used.
Telegram notifications are attached as an observer so notification failures
cannot alter or block the trading lifecycle.
"""
from __future__ import annotations

import logging
import os
import threading

from flask import Flask, jsonify

from pipeline.telegram_reporter import PaperTradeTelegramMonitor
from pipeline.trade_manager_paper_runner import TradeManagerPaperTradingRunner

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("ShadowTrading.Main")

app = Flask(__name__)
runner = TradeManagerPaperTradingRunner()
telegram_monitor = PaperTradeTelegramMonitor(runner)


@app.get("/")
def home():
    return jsonify({
        "status": "healthy",
        "mode": "PAPER",
        "trade_manager": "ACTIVE",
        "telegram_observer": "ACTIVE" if telegram_monitor.reporter.enabled else "DISABLED",
    }), 200


@app.get("/status")
def status():
    snapshot = runner.snapshot()
    snapshot["trade_manager"] = {
        "open_positions": len(runner.trade_manager.get_open_positions()),
        "hold_positions": len(runner.trade_manager.get_hold_positions()),
        "review_required": len(runner.trade_manager.get_review_required()),
    }
    snapshot["telegram"] = {
        "enabled": telegram_monitor.reporter.enabled,
        "token_source": "TOKEN" if os.getenv("TOKEN") else "TELEGRAM_TOKEN",
        "chat_id_source": "TELEGRAMID" if os.getenv("TELEGRAMID") else "TELEGRAM_CHAT_ID",
    }
    return jsonify(snapshot), 200


def _run_paper() -> None:
    try:
        runner.run_forever()
    except Exception:
        logger.exception("Paper trading runner stopped unexpectedly")


def _run_telegram_monitor() -> None:
    try:
        telegram_monitor.run_forever()
    except Exception:
        logger.exception("Telegram monitor stopped unexpectedly")


def start() -> None:
    paper_worker = threading.Thread(
        target=_run_paper,
        name="paper-trading-runner",
        daemon=True,
    )
    paper_worker.start()

    telegram_worker = threading.Thread(
        target=_run_telegram_monitor,
        name="telegram-paper-monitor",
        daemon=True,
    )
    telegram_worker.start()

    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    start()
