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


def _notify_closed_positions() -> int:
    """Send exactly-once SELL notifications for closed Paper positions.

    The execution lifecycle is authoritative: a notification is considered
    sent only after the position is already CLOSED and Telegram acknowledges
    the message. The sent marker is persisted with the position, so a restart
    retries genuinely unsent notifications without re-sending acknowledged
    ones.
    """
    sent = 0
    for position in runtime.repository.get_closed_positions():
        if position.exit_metadata.get("telegram_notification_sent"):
            continue
        reason = getattr(position.close_reason, "name", str(position.close_reason))
        exit_price = float(position.exit_metadata.get("exit_price", position.current_price))
        entry_value = float(position.entry_price) * float(position.quantity)
        pnl_pct = (float(position.gross_pnl) / entry_value * 100.0) if entry_value else 0.0
        message = (
            "=== PAPER SELL ===\n"
            f"Symbol: {position.symbol}\n"
            f"Reason: {reason}\n"
            f"Quantity: {position.quantity:.12f}\n"
            f"Entry: {position.entry_price:.8f}\n"
            f"Exit: {exit_price:.8f}\n"
            f"Gross P&L: {position.gross_pnl:+.4f}$\n"
            f"P&L %: {pnl_pct:+.2f}%\n"
            f"Fees: {position.total_fees:.4f}$\n"
            f"Net P&L: {position.realized_pnl:+.4f}$\n"
            f"Paper cash: ${runtime.execution_adapter.balance.cash:.2f}\n"
            "PAPER ONLY"
        )
        if _legacy.send_telegram_message(message):
            position.exit_metadata["telegram_notification_sent"] = True
            position.exit_metadata["telegram_notification_sent_at"] = time.time()
            runtime.repository.update(position)
            sent += 1
    return sent


async def _dual_mode_engine():
    _legacy.send_telegram_message(
        "🟢 Paper Trading dual-mode strategy engine started on Render\n"
        f"Universe: {len(TRADING_SYMBOLS)} Binance Spot USDT pairs\n"
        f"Scalp: 5m reversal + 15m context | threshold {SCALP_SCORE_THRESHOLD}\n"
        f"Swing: 15m macro + 5m confirmation | threshold {SWING_SCORE_THRESHOLD}\n"
        "Trade Manager: Parts 1-8\n"
        "No real exchange orders are submitted."
    )
    # Flush any SELL notifications that were successfully executed but not
    # acknowledged by Telegram before a previous process restart.
    _notify_closed_positions()
    while True:
        started = time.monotonic()
        try:
            await asyncio.to_thread(_legacy.process_market_cycle)
        except Exception:
            _legacy.logger.exception("Dual-mode paper market cycle failed")
        finally:
            # Exit notification is deliberately outside the strategy path: a
            # Telegram outage must never prevent Trade Manager state from being
            # CLOSED or prevent the next market cycle from running.
            try:
                _notify_closed_positions()
            except Exception:
                _legacy.logger.exception("Paper SELL notification reconciliation failed")
        elapsed = time.monotonic() - started
        await asyncio.sleep(max(1.0, _legacy.LOOP_SECONDS - elapsed))


if __name__ == "__main__":
    threading.Thread(target=_legacy._daily_report_loop, daemon=True, name="paper-daily-report").start()
    threading.Thread(target=lambda: asyncio.run(_dual_mode_engine()), daemon=True, name="dual-mode-market-engine").start()
    _legacy.run_flask()
