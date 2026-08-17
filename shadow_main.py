"""Paper Trading entrypoint with dual Scalping + Swing strategy lanes.

The original Shadow entrypoint is preserved in ``shadow_main_legacy.py``.
This thin adapter replaces only the strategy scoring contract. Trade Manager,
Paper Execution, persistence, Smart Hold, Recovery and the existing market
cycle remain owned by the legacy runtime.
"""
from __future__ import annotations
import asyncio
import threading
import time
from flask import jsonify
import shadow_main_legacy as _legacy
from shadow_main_legacy import *
from dual_mode_strategy import score_symbol, SCALP_SCORE_THRESHOLD, SWING_SCORE_THRESHOLD, BUY_SCORE_THRESHOLD

_legacy.score_symbol = score_symbol
_legacy.BUY_SCORE_THRESHOLD = BUY_SCORE_THRESHOLD
app = _legacy.app
runtime = _legacy.runtime
TRADING_SYMBOLS = _legacy.TRADING_SYMBOLS


def _home():
    positions = runtime.facade.get_open_positions()
    metrics = runtime.facade.get_metrics()
    return jsonify({
        "status": "healthy",
        "mode": "PAPER",
        "entrypoint": "shadow_main.py",
        "strategy": "SCALP 5m reversal + 15m context / SWING 15m macro + 5m confirmation",
        "trade_manager": "modular_parts_1_8",
        "symbols": TRADING_SYMBOLS,
        "open_positions": len(positions),
        "metrics": getattr(metrics, "__dict__", str(metrics)),
        "score_threshold": SWING_SCORE_THRESHOLD,
        "scalp_score_threshold": SCALP_SCORE_THRESHOLD,
        "swing_score_threshold": SWING_SCORE_THRESHOLD,
        "telegram_configured": bool(_legacy.TELEGRAM_TOKEN and _legacy.TELEGRAM_CHAT_ID),
    }), 200

app.view_functions["home"] = _home


async def _dual_mode_engine():
    _legacy.send_telegram_message(
        "🟢 Paper Trading dual-mode strategy engine started on Render\n"
        f"Universe: {len(TRADING_SYMBOLS)} Binance Spot USDT pairs\n"
        f"Scalp: 5m reversal + 15m context | threshold {SCALP_SCORE_THRESHOLD}\n"
        f"Swing: 15m macro + 5m confirmation | threshold {SWING_SCORE_THRESHOLD}\n"
        "Trade Manager: Parts 1-8\n"
        "No real exchange orders are submitted."
    )
    while True:
        started = time.monotonic()
        try:
            await asyncio.to_thread(_legacy.process_market_cycle)
        except Exception:
            _legacy.logger.exception("Dual-mode paper market cycle failed")
        elapsed = time.monotonic() - started
        await asyncio.sleep(max(1.0, _legacy.LOOP_SECONDS - elapsed))


if __name__ == "__main__":
    threading.Thread(target=_legacy._daily_report_loop, daemon=True, name="paper-daily-report").start()
    threading.Thread(target=lambda: asyncio.run(_dual_mode_engine()), daemon=True, name="dual-mode-market-engine").start()
    _legacy.run_flask()
