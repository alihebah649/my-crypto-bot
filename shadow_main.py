from __future__ import annotations

import asyncio
import threading

import shadow_main_base as _base

# PAPER ONLY entrypoint: no real exchange orders are submitted here.
_legacy = _base._legacy
runtime = _base.runtime
app = _base.app
TRADING_SYMBOLS = _base.TRADING_SYMBOLS
brain_shadow_runtime = _base.brain_shadow_runtime
SCALP_SCORE_THRESHOLD = _base.SCALP_SCORE_THRESHOLD
SWING_SCORE_THRESHOLD = _base.SWING_SCORE_THRESHOLD
BUY_SCORE_THRESHOLD = _base.BUY_SCORE_THRESHOLD
_active_trade_modes = _base._active_trade_modes
_lane_aware_has_position = _base._lane_aware_has_position
_original_runtime_open_position = _base._original_runtime_open_position
_current_trade_mode = _base._current_trade_mode


def _open_one_position(symbol: str, entry_price: float, stop_loss: float, mode: str):
    _current_trade_mode["value"] = mode
    position = _original_runtime_open_position(symbol, entry_price, stop_loss, trade_mode=mode)
    if position is not None:
        position.entry_metadata["trade_mode"] = mode
        position.metadata["trade_mode"] = mode
        runtime.repository.update(position)
    return position


def _open_position_with_selected_mode(symbol: str, entry_price: float, stop_loss: float):
    score = _legacy.latest_scores.get(symbol, {}) or {}
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
    return opened[0] if opened else None


runtime.open_position = _open_position_with_selected_mode

# Keep the original module's Flask routes, diagnostics, market loop, and
# shutdown/reporting behavior; only the entry orchestration is replaced here.
if __name__ == "__main__":
    threading.Thread(target=_legacy._daily_report_loop, daemon=True, name="paper-daily-report").start()
    threading.Thread(target=lambda: asyncio.run(_base._dual_mode_engine()), daemon=True, name="dual-mode-market-engine").start()
    _legacy.run_flask()
