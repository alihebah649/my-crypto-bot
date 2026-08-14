"""Canonical entry point for Shadow Trading Bot.

The legacy monolithic implementation has been removed from the entry point.
The bot now starts the paper-trading integration path explicitly and keeps
execution isolated behind PaperExecutionAdapter.
"""

from __future__ import annotations

import logging
import os
import threading

from flask import Flask, jsonify

from pipeline.paper_trading_runner import PaperTradingRunner


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("ShadowTrading.Main")

app = Flask(__name__)
runner = PaperTradingRunner()


@app.get("/")
def home():
    return jsonify({"status": "healthy", "mode": "PAPER"}), 200


@app.get("/status")
def status():
    return jsonify(runner.snapshot()), 200


def _run_paper() -> None:
    try:
        runner.run_forever()
    except Exception:
        logger.exception("Paper trading runner stopped unexpectedly")


def start() -> None:
    worker = threading.Thread(
        target=_run_paper,
        name="paper-trading-runner",
        daemon=True,
    )
    worker.start()

    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    start()
