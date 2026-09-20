from __future__ import annotations

import asyncio
import inspect
import json
import threading
import time
from copy import deepcopy
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
# The embedded base module has its own standalone __main__ block; suppress it
# while embedding so shadow_main.py can finish installing all overlays first.
_base_path = Path(__file__).with_name("shadow_main_base.py")
_exec_source = _base_path.read_text(encoding="utf-8")
globals()["_SHADOW_MAIN_EMBEDDED"] = True
try:
    exec(compile(_exec_source, str(_base_path), "exec"), globals(), globals())
finally:
    globals().pop("_SHADOW_MAIN_EMBEDDED", None)

from trade_manager.models import PositionStatus
from trade_manager.risk_manager import PositionExitDecision, PositionExitReason
from core.entry_freshness_audit import entry_execution_freshness_allowed
from core.paper_outcome_evidence import build_paper_outcome_evidence
from core.dual_lane_position_gate import block_for_existing_position
from core.brain_authority import GuardedBrainAuthority
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

_paper_original_notify_closed_positions = _notify_closed_positions
_paper_outcome_evidence_logged_ids: set[str] = set()


# Guarded Brain authority: this is a Paper-only decision gate. A BUY from the
# Brain is only a pre-Risk approval; Risk, Trade Manager and Execution remain
# mandatory downstream authorities.
brain_authority = GuardedBrainAuthority()
_brain_authority_store = BrainShadowCaptureStore(
    Path(getattr(runtime, "persistence_dir", None) or ".") / "brain_shadow" / "authority_captures.jsonl"
)
runtime.brain_authority = brain_authority
runtime.brain_authority_store = _brain_authority_store


def _brain_authority_entry_gate(symbol: str, score: dict, mode: str) -> bool:
    normalized = str(symbol).upper()
    lane = str(mode or "NONE").upper()
    lane_score = dict(score or {})
    lane_score["trade_mode"] = lane
    if lane == "SCALP":
        lane_score["signal"] = "BUY" if score.get("scalp_signal") == "BUY" else str(score.get("scalp_signal", "HOLD")).upper()
        if score.get("scalp_score") is not None:
            lane_score["score"] = score.get("scalp_score")
    elif lane == "SWING":
        lane_score["signal"] = "BUY" if score.get("swing_signal") == "BUY" else str(score.get("swing_signal", "HOLD")).upper()
        if score.get("swing_score") is not None:
            lane_score["score"] = score.get("swing_score")

    btc_guard = globals().get("_last_btc_guard", {})
    market_view = derive_market_breadth(
        _legacy.latest_scores,
        btc_crashing=bool(btc_guard.get("crashing")) if isinstance(btc_guard, dict) else False,
    )
    active_position = lane in _active_trade_modes(normalized)
    capture = (runtime.last_entry_diagnostics.get(normalized, {}) or {}).get(
        "entry_v2_shadow_by_mode", {}
    ) or {}
    lane_capture = capture.get(lane, {}) or {}
    capture_id = lane_capture.get("capture_id")

    record = brain_authority.evaluate_entry(
        normalized,
        lane_score,
        trade_mode=lane,
        market_regime=market_view.regime,
        existing_position=active_position,
        capture_id=capture_id,
    )
    record_dict = record.to_dict()
    trace = runtime.last_entry_diagnostics.setdefault(normalized, {"symbol": normalized})
    by_mode = trace.setdefault("brain_authority_by_mode", {})
    by_mode[lane] = record_dict
    trace["brain_authority"] = record_dict if len(by_mode) == 1 else by_mode
    trace["brain_authority_version"] = GuardedBrainAuthority.VERSION
    trace["brain_authority_market_regime"] = market_view.to_dict()

    try:
        if not _brain_authority_store.append(record_dict):
            runtime.last_entry_diagnostics.setdefault("__brain_authority__", {})[
                "persistence_error"
            ] = _brain_authority_store.last_error
    except Exception as exc:
        runtime.last_entry_diagnostics.setdefault("__brain_authority__", {})[
            "persistence_error"
        ] = f"{type(exc).__name__}: {exc}"

    if not record.allowed:
        trace["result"] = "REJECTED_BRAIN_AUTHORITY"
        trace["execution"] = "NOT_RUN"
        trace["brain_authority_rejection_reason"] = record.brain_reason
        _legacy.logger.info(
            "BRAIN AUTHORITY BLOCK %s mode=%s score=%.1f regime=%s reason=%s",
            normalized,
            lane,
            record.strategy_score,
            market_view.regime,
            record.brain_reason,
        )
    else:
        _legacy.logger.info(
            "BRAIN AUTHORITY PASS %s mode=%s score=%.1f regime=%s reason=%s; downstream Risk/TM/Execution required",
            normalized,
            lane,
            record.strategy_score,
            market_view.regime,
            record.brain_reason,
        )
    return bool(record.allowed)


def _find_brain_authority_record_for_capture(capture_id: str | None) -> dict | None:
    if not capture_id:
        return None
    try:
        records = _brain_authority_store.read_all()
    except Exception:
        records = []
    for record in reversed(records):
        if str(record.get("capture_id") or "") == str(capture_id):
            return dict(record)
    return None


def _find_brain_record_for_capture(capture_id: str | None) -> dict | None:
    if not capture_id:
        return None
    try:
        records = brain_shadow_store.read_all()
    except Exception:
        records = []
    for record in reversed(records):
        if str(record.get("capture_id") or "") == str(capture_id):
            return dict(record)
    return None


def _emit_paper_outcome_evidence() -> int:
    emitted = 0
    try:
        closed_positions = list(runtime.repository.get_closed_positions())
    except Exception:
        _legacy.logger.exception("Paper outcome evidence: failed to read closed positions")
        return 0

    for position in closed_positions:
        position_id = str(getattr(position, "position_id", "") or "")
        if not position_id or position_id in _paper_outcome_evidence_logged_ids:
            continue

        entry_metadata = getattr(position, "entry_metadata", {}) or {}
        capture_id = entry_metadata.get("entry_v2_shadow_capture_id")
        brain_record = _find_brain_record_for_capture(capture_id)
        brain_authority_record = _find_brain_authority_record_for_capture(capture_id)

        record = build_paper_outcome_evidence(
            position,
            brain_record=brain_record,
        )
        if brain_authority_record is not None:
            record["brain_authority"] = brain_authority_record
        _legacy.logger.info(
            "PAPER OUTCOME EVIDENCE %s",
            json.dumps(record, ensure_ascii=False, separators=(",", ":")),
        )

        _paper_outcome_evidence_logged_ids.add(position_id)
        emitted += 1
    return emitted


def _notify_closed_positions_with_evidence() -> int:
    _emit_paper_outcome_evidence()
    return _paper_original_notify_closed_positions()


_notify_closed_positions = _notify_closed_positions_with_evidence

def _lane_aware_existing_position_gate(symbol: str) -> bool:
    """Preserve one position per lane, not one position per symbol."""
    strategy = (
        _legacy.latest_scores.get(symbol, {})
        or _legacy.market_state.get(symbol, {})
        or {}
    )
    if not isinstance(strategy, dict):
        strategy = {}
    active_modes = _active_trade_modes(symbol)
    return block_for_existing_position(strategy, active_modes)


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
    # Reserve only the send slot under the lock. The Binance network request
    # must run after releasing it so one slow response cannot serialize all
    # concurrent Kline workers.
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
    score = _legacy.latest_scores.get(symbol, {}) or _legacy.market_state.get(symbol, {}) or {}
    if not isinstance(score, dict) or not _brain_authority_entry_gate(symbol, score, mode):
        return None
    # Freeze the exact candidate snapshot before any downstream execution work.
    # This prevents a concurrent scoring cycle from replacing the RSI/volume/
    # location evidence that later gets attached to the closed position.
    candidate_strategy_snapshot = deepcopy(score) if isinstance(score, dict) else {}
    candidate_snapshot_captured_at = time.time()
    freshness = candidate_strategy_snapshot.get("entry_freshness_5m") if isinstance(candidate_strategy_snapshot, dict) else None
    if not entry_execution_freshness_allowed(freshness, mode):
        trace = runtime.last_entry_diagnostics.setdefault(symbol, {"symbol": symbol})
        trace.update({
            "result": "REJECTED_STALE_ENTRY_DATA",
            "trade_mode": mode,
            "execution": "NOT_RUN",
            "entry_freshness_5m": freshness,
        })
        _legacy.logger.info(
            "ENTRY BLOCKED %s: stale 5m decision data mode=%s age=%ss",
            symbol,
            mode,
            (freshness or {}).get("decision_candle_age_seconds"),
        )
        return None
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
    # Keep older test/integration callables compatible while the real runtime
    # receives the frozen candidate snapshot explicitly.
    try:
        params = inspect.signature(_original_runtime_open_position).parameters
        accepts_snapshot = (
            "strategy_snapshot" in params
            or any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())
        )
    except (TypeError, ValueError):
        accepts_snapshot = True
    if accepts_snapshot:
        position = _original_runtime_open_position(
            symbol,
            entry_price,
            stop_loss,
            trade_mode=mode,
            strategy_snapshot=candidate_strategy_snapshot,
            strategy_snapshot_captured_at=candidate_snapshot_captured_at,
        )
    else:
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
        # At this point at least one Paper position was actually committed.
        # Record that authoritative result directly so an older rejection from
        # an earlier lane/precheck cannot survive into the final trace.
        trace["result"] = "POSITION_COMMITTED"
        trace["execution"] = "FILLED"
        trace["execution_outcome"] = {
            "positions_opened": list(trace["positions_opened"]),
            "trade_modes_opened": list(trace["trade_modes_opened"]),
        }
        trace["diagnostic_consistency"] = "CONSISTENT"
    return opened[0] if opened else None


def _record_btc_crash_guard(candles):
    result = _paper_original_btc_crash_guard(candles)
    _last_btc_guard["crashing"] = bool(result[0])
    _last_btc_guard["drop_percent"] = float(result[1])
    return result


_legacy.btc_crash_guard = _record_btc_crash_guard

from engine.entry_v2_runtime_capture import install as _install_entry_v2_runtime_capture

_entry_v2_runtime_capture = _install_entry_v2_runtime_capture(
    legacy=_legacy,
    runtime=runtime,
    mtf_candles=_mtf_candles,
    trading_symbols=TRADING_SYMBOLS,
    btc_guard_provider=lambda: _last_btc_guard,
)


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




@app.get("/paper/brain-authority")
def _brain_authority_diagnostics():
    records = _brain_authority_store.read_all()
    recent = records[-100:]
    blocked_by_reason: dict[str, int] = {}
    allowed = blocked = 0
    for record in records:
        if str(record.get("stage", "")) != "ENTRY_GATE":
            continue
        if bool(record.get("allowed")):
            allowed += 1
        else:
            blocked += 1
            reason = str(record.get("brain_reason") or "UNKNOWN")
            blocked_by_reason[reason] = blocked_by_reason.get(reason, 0) + 1
    return jsonify({
        "version": GuardedBrainAuthority.VERSION,
        "mode": "PAPER",
        "execution_gate_active": True,
        "risk_authority_preserved": True,
        "trade_manager_authority_preserved": True,
        "execution_authority_preserved": True,
        "in_memory": brain_authority.snapshot(),
        "persistent": _brain_authority_store.summary(),
        "persistent_entry_decisions": {
            "allowed": allowed,
            "blocked": blocked,
            "blocked_by_reason": dict(sorted(blocked_by_reason.items(), key=lambda item: (-item[1], item[0]))),
        },
        "recent": recent,
    }), 200

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
    original_has_position = runtime.controller.has_position
    runtime.controller.has_position = _lane_aware_existing_position_gate
    try:
        result = _paper_original_process_market_cycle()
    finally:
        runtime.controller.has_position = original_has_position
    try:
        shadow_summary = _entry_v2_runtime_capture.capture_cycle()
        runtime.last_entry_diagnostics.setdefault("__entry_v2_shadow__", {})["summary"] = shadow_summary
    except Exception:
        _legacy.logger.exception("Entry v2 shadow capture failed")
    if _last_btc_guard["crashing"]:
        for symbol, score in sorted((_legacy.latest_scores or {}).items(), key=lambda item: float(item[1].get("swing_score", 0.0) or 0.0), reverse=True):
            if not strong_bullish_btc_exception(score):
                continue
            # This exception is explicitly a SWING entry. Check only the
            # SWING lane; a separate SCALP position must not suppress it.
            if "SWING" in _active_trade_modes(symbol):
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
        f"last_weight_1m={snapshot.get('last_weight_1m')}",
        flush=True,
    )


# Diagnostic-only runtime tracing. It wraps the already active fetch wrappers
# and records cache HIT/EXPIRED/MISS plus cache refreshes without changing
# return values, timings, thresholds, or trading decisions.
try:
    from core.market_data_runtime_trace import install as _install_market_data_runtime_trace
    _market_data_runtime_trace_snapshot = _install_market_data_runtime_trace(
        legacy=_legacy,
        kline_cache=_kline_cache,
        kline_cache_lock=_kline_cache_lock,
        kline_cache_ttl=_KLINE_CACHE_TTL,
    )
except Exception as exc:  # pragma: no cover - diagnostic path must not break paper engine
    _legacy.logger.exception("Market-data runtime trace installation failed: %s", exc)
    _market_data_runtime_trace_snapshot = lambda: {"available": False, "error": str(exc)}


@app.get("/market-data-trace")
def _market_data_trace_endpoint():
    return jsonify(_market_data_runtime_trace_snapshot()), 200


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


# Diagnostic-only thread liveness state. This does not control trading; it only
# exposes whether the background Paper engine thread is still alive.
_dual_mode_engine_thread: threading.Thread | None = None
_dual_mode_engine_thread_last_exit: dict[str, object] = {}


def _run_dual_mode_engine_thread() -> None:
    global _dual_mode_engine_thread_last_exit
    try:
        asyncio.run(_dual_mode_engine())
    except BaseException as exc:
        _dual_mode_engine_thread_last_exit = {
            "at": time.time(),
            "exception_type": type(exc).__name__,
            "exception": str(exc),
        }
        runtime.last_entry_diagnostics.setdefault("__paper_loop__", {})["thread_exception"] = dict(_dual_mode_engine_thread_last_exit)
        _legacy.logger.exception("Dual-mode market engine thread terminated unexpectedly")
        raise
    else:
        _dual_mode_engine_thread_last_exit = {
            "at": time.time(),
            "exception_type": None,
            "exception": None,
            "reason": "ASYNC_ENGINE_RETURNED",
        }
        runtime.last_entry_diagnostics.setdefault("__paper_loop__", {})["thread_exit"] = dict(_dual_mode_engine_thread_last_exit)
        _legacy.logger.error("Dual-mode market engine thread returned unexpectedly; trading loop is no longer running")


def _paper_engine_thread_watchdog() -> None:
    while True:
        try:
            thread = _dual_mode_engine_thread
            alive = bool(thread is not None and thread.is_alive())
            heartbeat = runtime.last_entry_diagnostics.setdefault("__paper_loop__", {})
            heartbeat["thread_alive"] = alive
            heartbeat["thread_watchdog_at"] = time.time()
            if not alive and thread is not None:
                heartbeat["thread_failure_detected_at"] = time.time()
                heartbeat["thread_last_exit"] = dict(_dual_mode_engine_thread_last_exit)
                _legacy.logger.error(
                    "PAPER ENGINE WATCHDOG: dual-mode engine thread is NOT ALIVE last_exit=%s",
                    _dual_mode_engine_thread_last_exit,
                )
        except Exception:
            _legacy.logger.exception("Paper engine thread watchdog failed")
        time.sleep(30.0)


if __name__ == "__main__":
    threading.Thread(target=_legacy._daily_report_loop, daemon=True, name="paper-daily-report").start()
    threading.Thread(target=_market_health_loop, daemon=True, name="paper-market-health").start()
    _dual_mode_engine_thread = threading.Thread(
        target=_run_dual_mode_engine_thread,
        daemon=True,
        name="dual-mode-market-engine",
    )
    _dual_mode_engine_thread.start()
    threading.Thread(
        target=_paper_engine_thread_watchdog,
        daemon=True,
        name="paper-engine-thread-watchdog",
    ).start()
    _legacy.run_flask()