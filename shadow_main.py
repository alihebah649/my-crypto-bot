from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path

# PAPER ONLY entrypoint: execute the preserved original entrypoint in this
# module's namespace so all existing globals/tests keep their behavior.
_base_path = Path(__file__).with_name("shadow_main_base.py")
_exec_source = _base_path.read_text(encoding="utf-8")
exec(compile(_exec_source, str(_base_path), "exec"), globals(), globals())

from trade_manager.models import PositionStatus
from trade_manager.risk_manager import PositionExitDecision, PositionExitReason
from core.paper_risk_overlay import (
    BTC_RECOVERY_MAX_DRAWDOWN_PERCENT,
    REENTRY_COOLDOWN_SECONDS,
    loss_cooldown_remaining,
    profit_protection_trigger,
    strong_bullish_btc_exception,
    btc_recovery_eligible,
    btc_recovery_stop,
)

# Keep the original names populated by shadow_main_base.py intact for existing
# tests and compatibility. Capture our own aliases for anything we wrap.
_paper_original_process_market_cycle = _legacy.process_market_cycle
_paper_original_btc_crash_guard = _legacy.btc_crash_guard
_paper_original_run_exit_watchdog = runtime.run_exit_watchdog
_paper_original_facade_execute_decision = runtime.facade.execute_decision
_last_btc_guard = {"crashing": False, "drop_percent": 0.0}


def _loss_cooldown(symbol: str) -> float:
    return loss_cooldown_remaining(
        runtime.repository.get_closed_positions(),
        symbol,
        now=time.time(),
        cooldown_seconds=REENTRY_COOLDOWN_SECONDS,
    )


def _open_one_position(symbol: str, entry_price: float, stop_loss: float, mode: str):
    remaining = _loss_cooldown(symbol)
    if remaining > 0:
        trace = runtime.last_entry_diagnostics.setdefault(symbol, {"symbol": symbol})
        trace.update({
            "result": "REJECTED_LOSS_COOLDOWN",
            "loss_cooldown_seconds": round(remaining, 1),
            "loss_cooldown_hours": round(remaining / 3600.0, 2),
            "trade_mode": mode,
            "execution": "NOT_RUN",
        })
        _legacy.logger.info(
            "ENTRY BLOCKED %s: loss cooldown active for %.0fs mode=%s",
            symbol, remaining, mode,
        )
        return None

    _current_trade_mode["value"] = mode
    position = _original_runtime_open_position(
        symbol, entry_price, stop_loss, trade_mode=mode
    )
    if position is not None:
        position.entry_metadata["trade_mode"] = mode
        position.metadata["trade_mode"] = mode
        runtime.repository.update(position)
    return position


def _open_position_with_selected_mode(symbol: str, entry_price: float, stop_loss: float):
    score = _legacy.latest_scores.get(symbol, {}) or _legacy.market_state.get(symbol, {}) or {}
    modes = []
    if score.get("scalp_signal") == "BUY":
        modes.append("SCALP")
    if score.get("swing_signal") == "BUY":
        modes.append("SWING")
    if not modes:
        mode = str(score.get("trade_mode", "SWING")).upper()
        modes = [mode if mode in {"SCALP", "SWING"} else "SWING"]

    requested_modes = list(modes)
    active_modes = _active_trade_modes(symbol)
    skipped_existing = []
    opened = []
    for mode in requested_modes:
        if mode in active_modes:
            skipped_existing.append(mode)
            continue
        position = _open_one_position(symbol, entry_price, stop_loss, mode)
        if position is not None:
            opened.append(position)

    trace = runtime.last_entry_diagnostics.setdefault(symbol, {})
    trace["trade_modes_requested"] = requested_modes
    trace["trade_modes_skipped_existing"] = skipped_existing
    trace["trade_modes_opened"] = [
        str(p.entry_metadata.get("trade_mode", "SWING")).upper() for p in opened
    ]
    trace["positions_opened"] = [p.position_id for p in opened]
    trace["dual_lane_entry"] = len(opened) > 1
    if opened:
        trace["trade_mode"] = str(
            opened[0].entry_metadata.get("trade_mode", "SWING")
        ).upper()
    return opened[0] if opened else None


def _record_btc_crash_guard(candles):
    result = _paper_original_btc_crash_guard(candles)
    _last_btc_guard["crashing"] = bool(result[0])
    _last_btc_guard["drop_percent"] = float(result[1])
    return result


_legacy.btc_crash_guard = _record_btc_crash_guard


def _paper_stop_fill_wrapper(position_id: str, decision: PositionExitDecision):
    """Paper-only: model a stop breach as a fill at the configured stop.

    The existing controller/execution gateway intentionally submits a market
    SELL and therefore the Paper adapter uses the latest polled price. That is
    useful for execution plumbing, but it makes Paper stop-loss statistics
    include polling delay as artificial slippage. For a STOP_LOSS decision,
    temporarily use the configured stop as the Paper execution price.
    """
    if decision.reason is not PositionExitReason.STOP_LOSS:
        return _paper_original_facade_execute_decision(position_id, decision)

    position = runtime.repository.get(position_id)
    adapter = getattr(runtime, "execution_adapter", None)
    if position is None or adapter is None or not hasattr(adapter, "get_market_price"):
        return _paper_original_facade_execute_decision(position_id, decision)

    try:
        original_price = adapter.get_market_price(position.symbol)
    except Exception:
        return _paper_original_facade_execute_decision(position_id, decision)

    stop_price = float(position.stop_loss)
    current_price = float(position.current_price)
    if stop_price <= 0 or current_price >= stop_price:
        return _paper_original_facade_execute_decision(position_id, decision)

    try:
        adapter.set_market_price(position.symbol, stop_price)
        result = _paper_original_facade_execute_decision(position_id, decision)
        if result is not None and result.status is PositionStatus.CLOSED:
            result.exit_metadata["paper_stop_fill"] = True
            result.exit_metadata["paper_stop_price"] = stop_price
            result.exit_metadata["paper_observed_price_at_trigger"] = current_price
            runtime.repository.update(result)
        return result
    finally:
        try:
            adapter.set_market_price(position.symbol, original_price)
        except Exception:
            _legacy.logger.exception(
                "Unable to restore Paper market price after stop-fill simulation for %s",
                position.symbol,
            )


runtime.facade.execute_decision = _paper_stop_fill_wrapper


def _apply_paper_exit_protection() -> None:
    """Apply Paper-only protection before the normal independent watchdog."""
    active = [
        p for p in runtime.repository.get_open_positions()
        if p.status in {
            PositionStatus.OPEN,
            PositionStatus.HOLD,
            PositionStatus.REVIEW_REQUIRED,
            PositionStatus.PARTIALLY_CLOSED,
        }
    ]

    for position in active:
        current = float(position.current_price)
        if current <= 0 or position.entry_price <= 0:
            continue

        # Protection mode: once a meaningful profit existed, lock the move when
        # price retraces. This is intentionally earlier than the normal TP.
        if profit_protection_trigger(
            entry_price=position.entry_price,
            current_price=current,
            highest_price=position.highest_price,
            max_profit_percent=position.max_profit_percent,
        ):
            decision = PositionExitDecision(
                True,
                PositionExitReason.TRAILING_STOP,
                current,
                "Paper Protection: profitable retracement before TP",
            )
            result = runtime.facade.execute_decision(position.position_id, decision)
            if result is not None and result.status is PositionStatus.CLOSED:
                result.exit_metadata["paper_profit_protection"] = True
                runtime.repository.update(result)
            continue

        # BTC Recovery: do not turn an ordinary bounded pullback into a hard
        # loss when the BTC setup is still strong. The emergency floor remains
        # finite and is enforced by the normal STOP_LOSS path afterwards.
        if str(position.symbol).upper() != "BTCUSDT":
            continue

        score = (
            _legacy.latest_scores.get("BTCUSDT", {})
            or _legacy.market_state.get("BTCUSDT", {})
            or {}
        )
        pnl_percent = (
            (current - position.entry_price) / position.entry_price * 100.0
        )
        eligible = btc_recovery_eligible(
            score,
            btc_crashing=bool(_last_btc_guard["crashing"]),
            pnl_percent=pnl_percent,
            max_drawdown_percent=BTC_RECOVERY_MAX_DRAWDOWN_PERCENT,
        )
        if not eligible or current > position.stop_loss:
            continue

        emergency_stop = btc_recovery_stop(position.entry_price)
        position.metadata["initial_stop_loss"] = float(
            position.metadata.get("initial_stop_loss", position.stop_loss)
        )
        position.stop_loss = emergency_stop
        position.status = PositionStatus.HOLD
        position.entered_hold_at = position.entered_hold_at or time.time()
        position.hold_reason = "BTC_RECOVERY_OVERLAY"
        position.metadata["paper_risk_overlay"] = "BTC_RECOVERY"
        position.metadata["btc_recovery_emergency_stop"] = emergency_stop
        runtime.repository.update(position)

        trace = runtime.last_entry_diagnostics.setdefault("BTCUSDT", {})
        trace["btc_recovery"] = {
            "active": True,
            "pnl_percent": round(pnl_percent, 3),
            "emergency_stop": emergency_stop,
            "btc_crash_guard": False,
        }
        _legacy.logger.info(
            "BTC RECOVERY active: position=%s pnl=%.3f%% emergency_stop=%.8f",
            position.position_id,
            pnl_percent,
            emergency_stop,
        )


def _run_exit_watchdog_with_overlays():
    _apply_paper_exit_protection()
    return _paper_original_run_exit_watchdog()


runtime.run_exit_watchdog = _run_exit_watchdog_with_overlays


def _process_market_cycle_with_overlays():
    result = _paper_original_process_market_cycle()

    # The legacy BTC guard intentionally blocks all new entries during a crash.
    # Preserve that safety rule, with one deliberately narrow exception for a
    # very strong individual Swing setup.
    if _last_btc_guard["crashing"]:
        for symbol, score in sorted(
            (_legacy.latest_scores or {}).items(),
            key=lambda item: float(item[1].get("swing_score", 0.0) or 0.0),
            reverse=True,
        ):
            if not strong_bullish_btc_exception(score):
                continue
            if runtime.controller.has_position(symbol):
                continue

            price = float(score.get("price", 0.0) or 0.0)
            atr = float(score.get("atr", 0.0) or 0.0)
            if price <= 0 or atr <= 0:
                continue

            stop_loss = price - (2.0 * atr)
            if stop_loss <= 0:
                continue

            trace = runtime.last_entry_diagnostics.setdefault(
                symbol, {"symbol": symbol}
            )
            trace["btc_crash_guard_exception"] = True
            trace["btc_crash_guard_drop_percent"] = _last_btc_guard["drop_percent"]
            trace["btc_crash_guard_exception_reason"] = "STRONG_SWING_SETUP"

            runtime.open_position(symbol, price, stop_loss)

    return result


_legacy.process_market_cycle = _process_market_cycle_with_overlays
runtime.open_position = _open_position_with_selected_mode


if __name__ == "__main__":
    threading.Thread(
        target=_legacy._daily_report_loop,
        daemon=True,
        name="paper-daily-report",
    ).start()
    threading.Thread(
        target=lambda: asyncio.run(_dual_mode_engine()),
        daemon=True,
        name="dual-mode-market-engine",
    ).start()
    _legacy.run_flask()
