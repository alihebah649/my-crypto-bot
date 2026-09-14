from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path

# Explicitly load the existing process-wide Binance instrumentation before the
# legacy entrypoint is executed. Render starts this file directly with
# `python shadow_main.py`, so relying only on automatic sitecustomize discovery
# is not sufficient for guaranteed observability.
try:
    import sitecustomize as _binance_metrics
except Exception as exc:  # pragma: no cover - defensive runtime fallback
    _binance_metrics = None
    print(f"[BINANCE-METRICS] instrumentation_import_failed error={type(exc).__name__}: {exc}", flush=True)

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

_paper_original_process_market_cycle = _legacy.process_market_cycle
_paper_original_btc_crash_guard = _legacy.btc_crash_guard
_paper_original_run_exit_watchdog = runtime.run_exit_watchdog
_paper_original_facade_execute_decision = runtime.facade.execute_decision
_paper_original_24h_tickers = _legacy.fetch_24h_tickers
_last_btc_guard = {"crashing": False, "drop_percent": 0.0}

# A 24h ticker response is only used for current price, bid/ask and reporting
# volume. Keep a valid snapshot available through short Binance rate-limit
# windows; never fabricate a fresh market price when no prior snapshot exists.
_TICKER_CACHE_TTL = 300.0
_TICKER_STALE_MAX_AGE = 900.0
_ticker_cache: tuple[float, dict[str, dict]] | None = None
_ticker_cache_lock = threading.RLock()
_ticker_cache_hits = 0
_ticker_cache_misses = 0
_ticker_cache_stale_uses = 0
_ticker_cache_stale_active = False


def _guarded_fetch_24h_tickers_with_cache():
    global _ticker_cache, _ticker_cache_hits, _ticker_cache_misses, _ticker_cache_stale_uses, _ticker_cache_stale_active
    now = time.time()
    with _ticker_cache_lock:
        cached = _ticker_cache
        if cached is not None and now - cached[0] < _TICKER_CACHE_TTL:
            _ticker_cache_hits += 1
            _ticker_cache_stale_active = False
            return cached[1]
    _ticker_cache_misses += 1
    data = _paper_original_24h_tickers()
    if data:
        with _ticker_cache_lock:
            _ticker_cache = (time.time(), dict(data))
            _ticker_cache_stale_active = False
        return data
    # Binance can temporarily answer with 429/418; the underlying guard then
    # returns {}. Reuse only a bounded recent snapshot so the strategy is not
    # fed invented data and the normal retry path remains intact. The snapshot
    # remains diagnostic-only while stale: new paper entries are blocked.
    with _ticker_cache_lock:
        cached = _ticker_cache
        if cached is not None and now - cached[0] < _TICKER_STALE_MAX_AGE:
            _ticker_cache_stale_uses += 1
            _ticker_cache_stale_active = True
            return cached[1]
        _ticker_cache_stale_active = False
    return data


_legacy.fetch_24h_tickers = _guarded_fetch_24h_tickers_with_cache


def _ticker_cache_snapshot() -> dict:
    now = time.time()
    with _ticker_cache_lock:
        cached = _ticker_cache
        hits = _ticker_cache_hits
        misses = _ticker_cache_misses
        stale_uses = _ticker_cache_stale_uses
        stale_active = _ticker_cache_stale_active
    age = None if cached is None else max(0.0, now - cached[0])
    return {
        "entries": 0 if cached is None else len(cached[1]),
        "age_seconds": None if age is None else round(age, 1),
        "ttl_seconds": _TICKER_CACHE_TTL,
        "stale_max_age_seconds": _TICKER_STALE_MAX_AGE,
        "fresh": bool(age is not None and age < _TICKER_CACHE_TTL),
        "stale_active": stale_active,
        "hits": hits,
        "misses": misses,
        "stale_uses": stale_uses,
    }


_BINANCE_KLINE_MIN_INTERVAL = 0.25
_binance_kline_request_lock = threading.Lock()
_binance_kline_last_request_at = 0.0
_original_rate_limited_fetch_klines = _legacy.fetch_klines


def _rate_limited_fetch_klines(symbol: str, interval: str, limit: int):
    global _binance_kline_last_request_at
    with _binance_kline_request_lock:
        now = time.monotonic()
        wait = _BINANCE_KLINE_MIN_INTERVAL - (now - _binance_kline_last_request_at)
        if wait > 0:
            time.sleep(wait)
        _binance_kline_last_request_at = time.monotonic()
        return _original_rate_limited_fetch_klines(symbol, interval, limit)


_legacy.fetch_klines = _rate_limited_fetch_klines


def _loss_cooldown(symbol: str) -> float:
    return loss_cooldown_remaining(runtime.repository.get_closed_positions(), symbol, now=time.time(), cooldown_seconds=REENTRY_COOLDOWN_SECONDS)


def _open_one_position(symbol: str, entry_price: float, stop_loss: float, mode: str):
    with _ticker_cache_lock:
        stale_active = _ticker_cache_stale_active
    if stale_active:
        trace = runtime.last_entry_diagnostics.setdefault(symbol, {"symbol": symbol})
        trace.update({"result": "REJECTED_STALE_TICKER", "ticker_stale_active": True, "trade_mode": mode, "execution": "NOT_RUN"})
        _legacy.logger.info("ENTRY BLOCKED %s: stale ticker snapshot active mode=%s", symbol, mode)
        return None
    remaining = _loss_cooldown(symbol)
    if remaining > 0:
        trace = runtime.last_entry_diagnostics.setdefault(symbol, {"symbol": symbol})
        trace.update({"result": "REJECTED_LOSS_COOLDOWN", "loss_cooldown_seconds": round(remaining, 1), "loss_cooldown_hours": round(remaining / 3600.0, 2), "trade_mode": mode, "execution": "NOT_RUN"})
        _legacy.logger.info("ENTRY BLOCKED %s: loss cooldown active for %.0fs mode=%s", symbol, remaining, mode)
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
    result = _paper_original_btc_crash_guard(candles)
    _last_btc_guard["crashing"] = bool(result[0])
    _last_btc_guard["drop_percent"] = float(result[1])
    return result


_legacy.btc_crash_guard = _record_btc_crash_guard


def _paper_stop_fill_wrapper(position_id: str, decision: PositionExitDecision):
    protected_reasons = {PositionExitReason.STOP_LOSS, PositionExitReason.BREAK_EVEN}
    if decision.reason not in protected_reasons:
        return _paper_original_facade_execute_decision(position_id, decision)
    position = runtime.repository.get(position_id)
    if position is None:
        return _paper_original_facade_execute_decision(position_id, decision)
    observed_price = float(position.current_price)
    protected_price = float(position.stop_loss)
    result = _paper_original_facade_execute_decision(position_id, decision)
    if result is not None and result.status is PositionStatus.CLOSED:
        result.exit_metadata["paper_stop_fill"] = True
        result.exit_metadata["paper_stop_price"] = protected_price
        result.exit_metadata["paper_observed_price_at_trigger"] = observed_price
        result.exit_metadata["paper_stop_reason"] = decision.reason.name
        runtime.repository.update(result)
    return result


runtime.facade.execute_decision = _paper_stop_fill_wrapper


def _apply_paper_exit_protection() -> None:
    active = [p for p in runtime.repository.get_open_positions() if p.status in {PositionStatus.OPEN, PositionStatus.HOLD, PositionStatus.REVIEW_REQUIRED, PositionStatus.PARTIALLY_CLOSED}]
    for position in active:
        current = float(position.current_price)
        if current <= 0 or position.entry_price <= 0:
            continue
        if profit_protection_trigger(entry_price=position.entry_price, current_price=current, highest_price=position.highest_price, max_profit_percent=position.max_profit_percent):
            decision = PositionExitDecision(True, PositionExitReason.TRAILING_STOP, current, "Paper Protection: profitable retracement before TP")
            result = runtime.facade.execute_decision(position.position_id, decision)
            if result is not None and result.status is PositionStatus.CLOSED:
                result.exit_metadata["paper_profit_protection"] = True
                runtime.repository.update(result)
            continue
        if str(position.symbol).upper() != "BTCUSDT":
            continue
        score = _legacy.latest_scores.get("BTCUSDT", {}) or _legacy.market_state.get("BTCUSDT", {}) or {}
        pnl_percent = (current - position.entry_price) / position.entry_price * 100.0
        eligible = btc_recovery_eligible(score, btc_crashing=bool(_last_btc_guard["crashing"]), pnl_percent=pnl_percent, max_drawdown_percent=BTC_RECOVERY_MAX_DRAWDOWN_PERCENT)
        if not eligible or current > position.stop_loss:
            continue
        emergency_stop = btc_recovery_stop(position.entry_price)
        position.metadata["initial_stop_loss"] = float(position.metadata.get("initial_stop_loss", position.stop_loss))
        position.stop_loss = emergency_stop
        position.status = PositionStatus.HOLD
        position.entered_hold_at = position.entered_hold_at or time.time()
        position.hold_reason = "BTC_RECOVERY_OVERLAY"
        position.metadata["paper_risk_overlay"] = "BTC_RECOVERY"
        position.metadata["btc_recovery_emergency_stop"] = emergency_stop
        runtime.repository.update(position)
        trace = runtime.last_entry_diagnostics.setdefault("BTCUSDT", {})
        trace["btc_recovery"] = {"active": True, "pnl_percent": round(pnl_percent, 3), "emergency_stop": emergency_stop, "btc_crash_guard": False}
        _legacy.logger.info("BTC RECOVERY active: position=%s pnl=%.3f%% emergency_stop=%.8f", position.position_id, pnl_percent, emergency_stop)


def _run_exit_watchdog_with_overlays():
    _apply_paper_exit_protection()
    return _paper_original_run_exit_watchdog()


runtime.run_exit_watchdog = _run_exit_watchdog_with_overlays


def _process_market_cycle_with_overlays():
    result = _paper_original_process_market_cycle()
    if _last_btc_guard["crashing"]:
        for symbol, score in sorted((_legacy.latest_scores or {}).items(), key=lambda item: float(item[1].get("swing_score", 0.0) or 0.0), reverse=True):
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
            trace["btc_crash_guard_exception_reason"] = "STRONG_SWING_SETUP"
            _open_one_position(symbol, price, stop_loss, "SWING")
    return result


_legacy.process_market_cycle = _process_market_cycle_with_overlays
runtime.open_position = _open_position_with_selected_mode


_MARKET_HEALTH_STATE = "UNKNOWN"
_MARKET_HEALTH_LAST_ALERT_AT = 0.0
_MARKET_HEALTH_HEARTBEAT_SECONDS = 3600.0
_MARKET_HEALTH_LOCK = threading.Lock()


def _market_health_notify(state: str, detail: str, *, force: bool = False) -> None:
    global _MARKET_HEALTH_STATE, _MARKET_HEALTH_LAST_ALERT_AT
    now = time.time()
    with _MARKET_HEALTH_LOCK:
        changed = state != _MARKET_HEALTH_STATE
        heartbeat_due = (now - _MARKET_HEALTH_LAST_ALERT_AT) >= _MARKET_HEALTH_HEARTBEAT_SECONDS
        if not force and not changed and not heartbeat_due:
            return
        _MARKET_HEALTH_STATE = state
        _MARKET_HEALTH_LAST_ALERT_AT = now
    message = f"📡 PAPER MARKET HEALTH\nState: {state}\n{detail}\nPAPER ONLY"
    try:
        _legacy.send_telegram_message(message)
    except Exception:
        _legacy.logger.exception("Market health Telegram notification failed")


def _observe_market_health() -> None:
    snapshot = _market_data_guard_snapshot()
    data_count = len(_legacy.latest_scores or {})
    symbol_count = len(TRADING_SYMBOLS)
    status_code = snapshot.get("status_code")
    blocked = bool(snapshot.get("blocked"))
    last_path = snapshot.get("last_path") or ""
    retry_in = float(snapshot.get("blocked_for_seconds", 0.0) or 0.0)
    if status_code in {418, 429}:
        _market_health_notify(f"BINANCE RATE LIMIT {status_code}", f"Path: {last_path}\nRetry in: {retry_in:.0f}s\nData: {data_count}/{symbol_count}")
        return
    if blocked:
        _market_health_notify("BINANCE CIRCUIT OPEN", f"Local protection is waiting; data: {data_count}/{symbol_count}\nRetry window: {retry_in:.0f}s")
        return
    if data_count <= 0:
        _market_health_notify("MARKET DATA DOWN", f"No scored symbols available: 0/{symbol_count}\nLast guard status: {status_code or 'none'}")
        return
    _market_health_notify("MARKET DATA UP", f"Scored symbols: {data_count}/{symbol_count}\nKline cache: {snapshot.get('kline_cache_entries', 0)} entries")


def _binance_metrics_snapshot_safe() -> dict:
    if _binance_metrics is None:
        return {"available": False, "error": "instrumentation_module_unavailable"}
    try:
        snapshot = _binance_metrics.binance_metrics_snapshot()
        snapshot["available"] = True
        return snapshot
    except Exception as exc:  # pragma: no cover - defensive diagnostics path
        return {"available": False, "error": f"{type(exc).__name__}: {exc}"}


@app.get("/binance-metrics")
def _binance_metrics_endpoint():
    return jsonify(_binance_metrics_snapshot_safe()), 200


_BINANCE_METRICS_LAST_LOG_AT = 0.0
_BINANCE_METRICS_LOG_INTERVAL = 60.0


def _emit_binance_metrics_snapshot() -> None:
    global _BINANCE_METRICS_LAST_LOG_AT
    now = time.time()
    if now - _BINANCE_METRICS_LAST_LOG_AT < _BINANCE_METRICS_LOG_INTERVAL:
        return
    _BINANCE_METRICS_LAST_LOG_AT = now
    snapshot = _binance_metrics_snapshot_safe()
    path_counts = snapshot.get("path_counts", {})
    path_weight = snapshot.get("path_observed_weight_delta", {})
    print(
        "[BINANCE-METRICS-SNAPSHOT] "
        f"total={snapshot.get('total_requests_seen', 0)} "
        f"real={snapshot.get('real_outbound_requests', 0)} "
        f"synthetic={snapshot.get('synthetic_circuit_responses', 0)} "
        f"status={snapshot.get('status_counts', {})} "
        f"path_counts={path_counts} "
        f"path_weight_delta={path_weight} "
        f"weight_delta_sum={snapshot.get('observed_weight_delta_sum', 0)} "
        f"last_weight_1m={snapshot.get('last_weight_1m')}" ,
        flush=True,
    )


def _market_health_loop() -> None:
    # Give the engine time to complete its first cycle before declaring a data
    # outage. Then sample once per minute; notifications remain transition/
    # heartbeat based, so this does not create Telegram spam.
    time.sleep(30.0)
    while True:
        try:
            _observe_market_health()
            _emit_binance_metrics_snapshot()
        except Exception:
            _legacy.logger.exception("Market health observer failed")
        time.sleep(60.0)


if __name__ == "__main__":
    threading.Thread(target=_legacy._daily_report_loop, daemon=True, name="paper-daily-report").start()
    threading.Thread(target=_market_health_loop, daemon=True, name="paper-market-health").start()
    threading.Thread(target=lambda: asyncio.run(_dual_mode_engine()), daemon=True, name="dual-mode-market-engine").start()
    _legacy.run_flask()
