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
from core.paper_risk_overlay import (
    BTC_RECOVERY_MAX_DRAWDOWN_PERCENT,
    REENTRY_COOLDOWN_SECONDS,
    loss_cooldown_remaining,
    profit_protection_trigger,
    strong_bullish_btc_exception,
    btc_recovery_eligible,
    btc_recovery_stop,
)

_original_runtime_open_position = runtime.open_position
_original_runtime_evaluate_position = runtime.evaluate_position
_original_btc_crash_guard = _legacy.btc_crash_guard
_original_process_market_cycle = _legacy.process_market_cycle
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
    position = _original_runtime_open_position(symbol, entry_price, stop_loss, trade_mode=mode)
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
    trace["trade_modes_opened"] = [str(p.entry_metadata.get("trade_mode", "SWING")).upper() for p in opened]
    trace["positions_opened"] = [p.position_id for p in opened]
    trace["dual_lane_entry"] = len(opened) > 1
    if opened:
        trace["trade_mode"] = str(opened[0].entry_metadata.get("trade_mode", "SWING")).upper()
    return opened[0] if opened else None


def _record_btc_crash_guard(candles):
    result = _original_btc_crash_guard(candles)
    _last_btc_guard["crashing"] = bool(result[0])
    _last_btc_guard["drop_percent"] = float(result[1])
    return result


_legacy.btc_crash_guard = _record_btc_crash_guard


def _evaluate_position_with_protection(symbol: str) -> None:
    """Paper-only overlay before the unchanged Trade Manager evaluation.

    - Profitable retracements can be protected before TP.
    - BTC can enter Recovery through a bounded 1.20% emergency floor when its
      individual setup remains strong and BTC itself is not crashing.
    - All other positions retain the existing Trade Manager exit ordering.
    """
    active = [
        p for p in runtime.repository.get_by_symbol(symbol)
        if p.status in {PositionStatus.OPEN, PositionStatus.HOLD}
    ]
    deferred = set()

    score = _legacy.market_state.get(str(symbol).upper(), {}) or _legacy.latest_scores.get(str(symbol).upper(), {}) or {}
    for position in active:
        current = float(position.current_price)
        pnl_percent = ((current - position.entry_price) / position.entry_price * 100.0) if position.entry_price > 0 else 0.0

        if profit_protection_trigger(
            entry_price=position.entry_price,
            current_price=current,
            highest_price=position.highest_price,
            max_profit_percent=position.max_profit_percent,
        ):
            decision = runtime.position_risk.evaluate(position)
            # If normal trailing already wants to exit, keep its authoritative
            # decision; otherwise use the earlier protection exit.
            if not decision.should_exit:
                from trade_manager.risk_manager import PositionExitDecision, PositionExitReason
                decision = PositionExitDecision(
                    True,
                    PositionExitReason.TRAILING_STOP,
                    current,
                    "Paper Protection: profitable retracement before TP",
                )
            runtime.facade.execute_decision(position.position_id, decision)
            continue

        if str(position.symbol).upper() == "BTCUSDT":
            eligible = btc_recovery_eligible(
                score,
                btc_crashing=bool(_last_btc_guard["crashing"]),
                pnl_percent=pnl_percent,
                max_drawdown_percent=BTC_RECOVERY_MAX_DRAWDOWN_PERCENT,
            )
            if eligible and current <= position.stop_loss:
                initial_stop = float(position.metadata.get("initial_stop_loss", position.stop_loss))
                position.metadata["initial_stop_loss"] = initial_stop
                position.stop_loss = btc_recovery_stop(position.entry_price)
                position.status = PositionStatus.HOLD
                position.entered_hold_at = position.entered_hold_at or time.time()
                position.hold_reason = "BTC_RECOVERY_OVERLAY"
                position.metadata["paper_risk_overlay"] = "BTC_RECOVERY"
                position.metadata["btc_recovery_emergency_stop"] = position.stop_loss
                runtime.repository.update(position)
                deferred.add(position.position_id)
                trace = runtime.last_entry_diagnostics.setdefault("BTCUSDT", {})
                trace["btc_recovery"] = {
                    "active": True,
                    "pnl_percent": round(pnl_percent, 3),
                    "emergency_stop": position.stop_loss,
                    "btc_crash_guard": False,
                }
                _legacy.logger.info(
                    "BTC RECOVERY active: position=%s pnl=%.3f%% emergency_stop=%.8f",
                    position.position_id, pnl_percent, position.stop_loss,
                )

    # Evaluate every position not deferred by the BTC recovery overlay.
    for position in runtime.repository.get_by_symbol(symbol):
        if position.position_id in deferred:
            continue
        if position.status not in {PositionStatus.OPEN, PositionStatus.HOLD}:
            continue
        decision = runtime.position_risk.evaluate(position)
        runtime.facade.execute_decision(position.position_id, decision)
    runtime.loss_ledger.sync(runtime.repository.get_closed_positions())


runtime.evaluate_position = _evaluate_position_with_protection


def _process_market_cycle_with_overlays():
    result = _original_process_market_cycle()
    # The legacy cycle intentionally blocks all entries during a BTC crash.
    # Re-open the gate only for exceptionally strong individual setups, after
    # the normal cycle has completed and only through the same Paper risk path.
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
            trace = runtime.last_entry_diagnostics.setdefault(symbol, {"symbol": symbol})
            trace["btc_crash_guard_exception"] = True
            trace["btc_crash_guard_drop_percent"] = _last_btc_guard["drop_percent"]
            runtime.open_position(symbol, price, stop_loss)
    return result


_legacy.process_market_cycle = _process_market_cycle_with_overlays
runtime.open_position = _open_position_with_selected_mode

if __name__ == "__main__":
    threading.Thread(target=_legacy._daily_report_loop, daemon=True, name="paper-daily-report").start()
    threading.Thread(target=lambda: asyncio.run(_dual_mode_engine()), daemon=True, name="dual-mode-market-engine").start()
    _legacy.run_flask()
