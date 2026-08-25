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
from dataclasses import replace
from flask import jsonify
import shadow_main_legacy as _legacy
from shadow_main_legacy import *
from dual_mode_strategy import score_symbol, SCALP_SCORE_THRESHOLD, SWING_SCORE_THRESHOLD, BUY_SCORE_THRESHOLD
from core.brain_shadow_runtime import BrainShadowRuntime

_legacy.score_symbol = score_symbol
_legacy.BUY_SCORE_THRESHOLD = BUY_SCORE_THRESHOLD
app = _legacy.app
runtime = _legacy.runtime
TRADING_SYMBOLS = _legacy.TRADING_SYMBOLS
brain_shadow_runtime = BrainShadowRuntime()

# -----------------------------------------------------------------------------
# Daily report: show realized net P&L only, without capital/cash in the result.
# -----------------------------------------------------------------------------
_original_build_daily_report = _legacy.build_daily_report


def _net_only_daily_report(date_key=None) -> str:
    report = _original_build_daily_report(date_key)
    lines = [line for line in report.splitlines() if not line.startswith("💵 Paper cash:")]
    report = "\n".join(lines)
    return report.replace("TOTAL", "NET P&L", 1)


_legacy.build_daily_report = _net_only_daily_report

# -----------------------------------------------------------------------------
# Dual-mode Trade Manager boundary
# -----------------------------------------------------------------------------
_current_trade_mode = {"value": "SWING"}
_original_controller_evaluate = runtime.risk_controller.evaluate
_original_portfolio_snapshot = runtime.portfolio_provider.snapshot
_original_runtime_open_position = runtime.open_position
_original_send_telegram_message = _legacy.send_telegram_message


def _mode_aware_risk_evaluate(*, account, symbol, signal, market, symbol_exposure=None, correlation_score=0.0):
    mode = _current_trade_mode["value"]
    return _original_controller_evaluate(
        account=account,
        symbol=symbol,
        signal=mode,
        market=market,
        symbol_exposure=symbol_exposure,
        correlation_score=correlation_score,
    )


runtime.risk_controller.evaluate = _mode_aware_risk_evaluate


def _lane_aware_portfolio_snapshot():
    snapshot = _original_portfolio_snapshot()
    active = [
        p for p in runtime.repository.get_open_positions()
        if p.status.name in {"OPEN", "HOLD", "REVIEW_REQUIRED", "PARTIALLY_CLOSED"}
    ]
    scalp_count = sum(1 for p in active if str(p.entry_metadata.get("trade_mode", "SWING")).upper() == "SCALP")
    swing_count = sum(1 for p in active if str(p.entry_metadata.get("trade_mode", "SWING")).upper() == "SWING")
    return replace(snapshot, scalp_open_positions=scalp_count, swing_open_positions=swing_count)


runtime.portfolio_provider.snapshot = _lane_aware_portfolio_snapshot


def _open_position_with_selected_mode(symbol: str, entry_price: float, stop_loss: float):
    mode = str(_legacy.latest_scores.get(symbol, {}).get("trade_mode", "SWING")).upper()
    if mode not in {"SCALP", "SWING"}:
        mode = "SWING"
    _current_trade_mode["value"] = mode
    position = _original_runtime_open_position(symbol, entry_price, stop_loss, trade_mode=mode)
    if position is not None:
        position.entry_metadata["trade_mode"] = mode
        position.metadata["trade_mode"] = mode
        runtime.repository.update(position)
        runtime.last_entry_diagnostics.setdefault(symbol, {})["trade_mode"] = mode
    return position


runtime.open_position = _open_position_with_selected_mode


def _send_telegram_with_trade_type(message: str) -> bool:
    if message.startswith("=== PAPER BUY ==="):
        symbol = ""
        for line in message.splitlines():
            if line.startswith("Symbol:"):
                symbol = line.split(":", 1)[1].strip().upper()
                break
        mode = str(_legacy.latest_scores.get(symbol, {}).get("trade_mode", _current_trade_mode["value"])).upper()
        if mode not in {"SCALP", "SWING"}:
            mode = _current_trade_mode["value"]
        lines = message.splitlines()
        try:
            symbol_index = next(i for i, line in enumerate(lines) if line.startswith("Symbol:"))
            lines.insert(symbol_index + 1, f"Trade Type: {mode}")
            message = "\n".join(lines)
        except StopIteration:
            pass
    return _original_send_telegram_message(message)


_legacy.send_telegram_message = _send_telegram_with_trade_type


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
        "scalp_open_positions": sum(1 for p in positions if str(p.entry_metadata.get("trade_mode", "SWING")).upper() == "SCALP"),
        "swing_open_positions": sum(1 for p in positions if str(p.entry_metadata.get("trade_mode", "SWING")).upper() == "SWING"),
        "scalp_max_open_positions": runtime.risk_config.exposure.max_scalp_positions,
        "swing_max_open_positions": runtime.risk_config.exposure.max_swing_positions,
        "metrics": getattr(metrics, "__dict__", str(metrics)),
        "score_threshold": SWING_SCORE_THRESHOLD,
        "scalp_score_threshold": SCALP_SCORE_THRESHOLD,
        "swing_score_threshold": SWING_SCORE_THRESHOLD,
        "telegram_configured": bool(_legacy.TELEGRAM_TOKEN and _legacy.TELEGRAM_CHAT_ID),
        "exit_watchdog": runtime.last_exit_watchdog,
        "brain_shadow": brain_shadow_runtime.snapshot(),
    }), 200

app.view_functions["home"] = _home


def _notify_closed_positions() -> int:
    """Send exactly-once SELL notifications for closed Paper positions."""
    sent = 0
    for position in runtime.repository.get_closed_positions():
        if position.exit_metadata.get("telegram_notification_sent"):
            continue
        reason = getattr(position.close_reason, "name", str(position.close_reason))
        exit_price = float(position.exit_metadata.get("exit_price", position.current_price))
        exit_message = str(position.exit_metadata.get("exit_message", "")).strip()
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
            + (f"Exit details: {exit_message}\n" if exit_message else "")
            + f"Paper cash: ${runtime.execution_adapter.balance.cash:.2f}\n"
            "PAPER ONLY"
        )
        if _legacy.send_telegram_message(message):
            position.exit_metadata["telegram_notification_sent"] = True
            position.exit_metadata["telegram_notification_sent_at"] = time.time()
            runtime.repository.update(position)
            sent += 1
    return sent


def _sanitize_entry_diagnostics() -> None:
    for trace in runtime.last_entry_diagnostics.values():
        result = str(trace.get("result", ""))
        if result.startswith("REJECTED_"):
            trace["execution"] = "NOT_RUN"
            trace["execution_outcome"] = None
            trace["facade"] = "NOT_RUN"
            trace.pop("facade_diagnostic", None)
            trace.pop("position_id", None)


def _run_brain_shadow_cycle() -> None:
    """Evaluate Brain beside strategy output; never alter trading authority."""
    latest = getattr(_legacy, "latest_scores", {}) or {}
    open_symbols = {
        str(position.symbol).upper()
        for position in runtime.repository.get_open_positions()
        if position.status.name in {"OPEN", "HOLD", "REVIEW_REQUIRED", "PARTIALLY_CLOSED"}
    }
    for symbol, strategy in latest.items():
        try:
            record = brain_shadow_runtime.evaluate_entry(
                str(symbol).upper(),
                strategy,
                existing_position=str(symbol).upper() in open_symbols,
            )
            runtime.last_entry_diagnostics.setdefault(str(symbol).upper(), {})["brain_shadow"] = record.to_dict()
            if not record.agreement:
                _legacy.logger.info(
                    "Brain shadow disagreement: symbol=%s mode=%s strategy=%s score=%.1f brain=%s confidence=%.2f reason=%s",
                    record.symbol,
                    record.trade_mode,
                    record.strategy_action,
                    record.strategy_score,
                    record.brain_action,
                    record.brain_confidence,
                    record.brain_reason,
                )
        except Exception:
            _legacy.logger.exception("Brain shadow evaluation failed for %s", symbol)


async def _dual_mode_engine():
    _legacy.send_telegram_message(
        "🟢 Paper Trading dual-mode strategy engine started on Render\n"
        f"Universe: {len(TRADING_SYMBOLS)} Binance Spot USDT pairs\n"
        f"Scalp: 5m reversal + 15m context | threshold {SCALP_SCORE_THRESHOLD} | max open 15\n"
        f"Swing: 15m macro + 5m confirmation | threshold {SWING_SCORE_THRESHOLD} | max open 10\n"
        "Trade Manager: Parts 1-8\n"
        "Brain: SHADOW ONLY — no execution authority\n"
        "No real exchange orders are submitted."
    )
    _notify_closed_positions()
    while True:
        started = time.monotonic()
        try:
            await asyncio.to_thread(_legacy.process_market_cycle)
            _run_brain_shadow_cycle()
            # Independent lifecycle pass: exit management must not depend on
            # the entry scanner or on a BUY signal for the same symbol.
            watchdog = runtime.run_exit_watchdog()
            if watchdog.exit_signals or watchdog.failed:
                _legacy.logger.info(
                    "Exit watchdog: evaluated=%d signals=%d closed=%d failed=%d",
                    watchdog.evaluated, watchdog.exit_signals, watchdog.closed, watchdog.failed,
                )
            _sanitize_entry_diagnostics()
        except Exception:
            _legacy.logger.exception("Dual-mode paper market cycle failed")
        finally:
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
