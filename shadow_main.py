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
# This entrypoint owns the active MarketDataManager. The core package bootstrap
# must not install a competing background manager during import.
globals()["_SHADOW_MAIN_MANAGES_MARKET_DATA"] = True
try:
    exec(compile(_exec_source, str(_base_path), "exec"), globals(), globals())
finally:
    globals().pop("_SHADOW_MAIN_EMBEDDED", None)

from trade_manager.models import PositionStatus
from trade_manager.risk_manager import PositionExitDecision, PositionExitReason
from core.entry_freshness_audit import entry_execution_freshness_allowed
from core.entry_decision_attribution import build_entry_decision_chain
from core.paper_outcome_evidence import build_paper_outcome_evidence
from core.dual_lane_position_gate import block_for_existing_position
from core.brain_authority import GuardedBrainAuthority
from core.postgres_evidence_store import PostgresEvidenceStore, database_url_from_env
from core.paper_engine_health import snapshot as _paper_engine_health_snapshot
from core.binance_rest_ws_comparison import compare_rest_ws_candle
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
_evidence_database_url = database_url_from_env()
if _evidence_database_url:
    _brain_authority_store = PostgresEvidenceStore(
        _evidence_database_url,
        evidence_type="BRAIN_AUTHORITY",
        max_records=50_000,
    )
else:
    _brain_authority_store = BrainShadowCaptureStore(
        Path(getattr(runtime, "persistence_dir", None) or ".") / "brain_shadow" / "authority_captures.jsonl"
    )
_paper_outcome_store = (
    PostgresEvidenceStore(
        _evidence_database_url,
        evidence_type="PAPER_OUTCOME",
        max_records=50_000,
    )
    if _evidence_database_url
    else None
)
runtime.brain_authority = brain_authority
runtime.brain_authority_store = _brain_authority_store


def _probe_paper_evidence_store() -> None:
    if _paper_outcome_store is None:
        return
    try:
        summary = _paper_outcome_store.summary()
        _legacy.logger.warning(
            "PAPER EVIDENCE STORAGE PROBE backend=%s status=READY records=%s",
            summary.get("backend"),
            summary.get("record_count"),
        )
    except Exception as exc:
        _legacy.logger.error(
            "PAPER EVIDENCE STORAGE PROBE backend=POSTGRES status=FAILED error=%s",
            f"{type(exc).__name__}: {exc}",
        )


threading.Thread(
    target=_probe_paper_evidence_store,
    daemon=True,
    name="paper-evidence-store-probe",
).start()

_legacy.logger.info(
    "PAPER EVIDENCE STORAGE backend=%s paper_outcome=%s brain_authority=%s brain_shadow=%s",
    "POSTGRES" if _evidence_database_url else "LOCAL_JSONL",
    "POSTGRES" if _paper_outcome_store is not None else "LOCAL_LOG_ONLY",
    "POSTGRES" if _evidence_database_url else "LOCAL_JSONL",
    "POSTGRES" if _evidence_database_url else "LOCAL_JSONL",
)


def _brain_authority_entry_gate(symbol: str, score: dict, mode: str) -> bool:
    normalized = str(symbol).upper()
    lane = str(mode or "NONE").upper()
    lane_score = dict(score or {})
    lane_score["trade_mode"] = lane
    if lane == "SCALP":
        scalp_signal = score.get("scalp_signal")
        if scalp_signal is None and str(score.get("trade_mode", "")).upper() == "SCALP":
            scalp_signal = score.get("signal")
        lane_score["signal"] = str(scalp_signal or "HOLD").upper()
        scalp_score = score.get("scalp_score")
        if scalp_score is None and str(score.get("trade_mode", "")).upper() == "SCALP":
            scalp_score = score.get("score")
        if scalp_score is not None:
            lane_score["score"] = scalp_score
            lane_score["scalp_score"] = scalp_score
    elif lane == "SWING":
        swing_signal = score.get("swing_signal")
        if swing_signal is None and str(score.get("trade_mode", "")).upper() == "SWING":
            swing_signal = score.get("signal")
        lane_score["signal"] = str(swing_signal or "HOLD").upper()
        swing_score = score.get("swing_score")
        if swing_score is None and str(score.get("trade_mode", "")).upper() == "SWING":
            swing_score = score.get("score")
        if swing_score is not None:
            lane_score["score"] = swing_score
            lane_score["swing_score"] = swing_score

    # The live dual-lane strategy supplies lane scores and reversal/recovery
    # fields. Older integration tests/callers may only supply a top-level
    # signal/score; do not invent a Brain judgment from missing context.
    context_complete = (
        (
            lane == "SWING"
            and lane_score.get("score") is not None
            and (
                "swing_signal" in score
                or str(score.get("trade_mode", "")).upper() == "SWING"
            )
        )
        or (
            lane == "SCALP"
            and lane_score.get("score") is not None
            and (
                "scalp_confirmed_reversal" in score
                or "scalp_recovery_confirmation" in score
            )
        )
    )
    if not context_complete:
        trace = runtime.last_entry_diagnostics.setdefault(symbol, {"symbol": symbol})
        trace.setdefault("brain_authority_by_mode", {})[lane] = {
            "authority_version": GuardedBrainAuthority.VERSION,
            "symbol": str(symbol).upper(),
            "trade_mode": lane,
            "stage": "ENTRY_GATE",
            "decision_state": "BYPASS_INCOMPLETE_CONTEXT",
            "reason": "BRAIN_CONTEXT_INCOMPLETE",
            "allowed": True,
        }
        return True

    btc_guard = globals().get("_last_btc_guard", {})
    market_view = derive_market_breadth(
        _legacy.latest_scores,
        btc_crashing=bool(btc_guard.get("crashing")) if isinstance(btc_guard, dict) else False,
    )
    repository = getattr(runtime, "repository", None)
    get_by_symbol = getattr(repository, "get_by_symbol", None)
    active_position = (
        lane in _active_trade_modes(normalized)
        if callable(get_by_symbol)
        else False
    )
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
        # Prefer the entry-cycle Brain Shadow snapshot bound to this position.
        # Fallback to the durable store for older positions created before the
        # binding fix.
        brain_record = entry_metadata.get("brain_shadow_entry")
        if not isinstance(brain_record, dict):
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

        if _paper_outcome_store is not None:
            try:
                if not _paper_outcome_store.append(record):
                    _legacy.logger.error(
                        "Paper outcome evidence persistence failed position=%s error=%s",
                        position_id,
                        _paper_outcome_store.last_error,
                    )
            except Exception:
                _legacy.logger.exception(
                    "Paper outcome evidence persistence raised position=%s",
                    position_id,
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

# A 24h ticker snapshot is assembled from staggered 11-symbol Binance batches.
# The merged cache keeps the full 22-symbol universe available while each group
# is refreshed every 30 seconds; no strategy thresholds or entry rules change.
_TICKER_CACHE_TTL = 30.0
_TICKER_STALE_MAX_AGE = 900.0
_ticker_cache: tuple[float, dict[str, dict]] | None = None
_ticker_cache_lock = threading.RLock()
_ticker_cache_hits = 0
_ticker_cache_misses = 0
_ticker_cache_stale_uses = 0
_ticker_cache_stale_active = False


def _fetch_ticker_group_from_binance(symbols: list[str]) -> dict[str, dict]:
    symbols = [str(symbol).upper() for symbol in symbols]
    symbols_json = json.dumps(symbols, separators=(",", ":"))
    try:
        data = _legacy._binance_get("/api/v3/ticker/24hr", {"symbols": symbols_json})
    except requests.HTTPError as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status in {418, 429}:
            _set_binance_block(exc, "/api/v3/ticker/24hr")
            return {}
        raise
    if not isinstance(data, list):
        return {}
    return {
        str(item.get("symbol", "")).upper(): item
        for item in data
        if str(item.get("symbol", "")).upper() in symbols
    }


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
    manager = globals().get("_market_data_manager")
    if manager is not None and not _binance_guard_active():
        try:
            manager.refresh_ticker_group(_fetch_ticker_group_from_binance, now=now)
            data = manager.merged_ticker_snapshot()
            if data:
                with _ticker_cache_lock:
                    _ticker_cache = (time.time(), dict(data))
                    _ticker_cache_stale_active = False
                return data
        except Exception:
            _legacy.logger.exception("MarketDataManager ticker refresh failed")

    data = _paper_original_24h_tickers()
    if data:
        with _ticker_cache_lock:
            _ticker_cache = (time.time(), dict(data))
            _ticker_cache_stale_active = False
        return data

    # Binance can temporarily answer with 429/418; reuse only a bounded recent
    # snapshot so the strategy is never fed invented data. New paper entries
    # remain blocked while this fallback snapshot is stale.
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


def _entry_decision_chain_for(symbol: str, mode: str, score: dict, *, final_approved: bool | None = None,
                              execution_attempted: bool = False, position_opened: bool = False,
                              failed_gate: str | None = None) -> dict:
    trace = runtime.last_entry_diagnostics.get(symbol, {}) or {}
    brain_by_mode = trace.get("brain_authority_by_mode", {}) or {}
    v2_by_mode = trace.get("entry_v2_shadow_by_mode", {}) or {}
    return build_entry_decision_chain(
        score,
        trade_mode=mode,
        brain_record=brain_by_mode.get(str(mode).upper()),
        v2_record=v2_by_mode.get(str(mode).upper()),
        final_approved=final_approved,
        execution_attempted=execution_attempted,
        position_opened=position_opened,
        failed_gate=failed_gate,
    )


def _open_one_position(symbol: str, entry_price: float, stop_loss: float, mode: str):
    score = _legacy.latest_scores.get(symbol, {}) or _legacy.market_state.get(symbol, {}) or {}
    # Freeze the exact candidate snapshot before Brain and all downstream work.
    # The same immutable observation is therefore used for Brain authority and
    # the Entry v2 / Paper outcome evidence attached to the position.
    candidate_strategy_snapshot = deepcopy(score) if isinstance(score, dict) else {}
    candidate_snapshot_captured_at = time.time()
    freshness = candidate_strategy_snapshot.get("entry_freshness_5m") if isinstance(candidate_strategy_snapshot, dict) else None

    def _record_chain(*, final_approved: bool | None, execution_attempted: bool,
                      position_opened: bool, failed_gate: str | None = None) -> dict:
        chain = _entry_decision_chain_for(
            symbol,
            mode,
            candidate_strategy_snapshot,
            final_approved=final_approved,
            execution_attempted=execution_attempted,
            position_opened=position_opened,
            failed_gate=failed_gate,
        )
        runtime.last_entry_diagnostics.setdefault(symbol, {})["entry_decision_chain"] = chain
        return chain

    if not entry_execution_freshness_allowed(freshness, mode):
        trace = runtime.last_entry_diagnostics.setdefault(symbol, {"symbol": symbol})
        trace.update({
            "result": "REJECTED_STALE_ENTRY_DATA",
            "trade_mode": mode,
            "execution": "NOT_RUN",
            "entry_freshness_5m": freshness,
        })
        _record_chain(final_approved=False, execution_attempted=False, position_opened=False, failed_gate="STALE_ENTRY_DATA")
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
        _record_chain(final_approved=False, execution_attempted=False, position_opened=False, failed_gate="STALE_TICKER")
        _legacy.logger.info("ENTRY BLOCKED %s: stale ticker snapshot active mode=%s", symbol, mode)
        return None
    remaining = _loss_cooldown(symbol)
    if remaining > 0:
        trace = runtime.last_entry_diagnostics.setdefault(symbol, {"symbol": symbol})
        trace.update({"result": "REJECTED_LOSS_COOLDOWN", "loss_cooldown_seconds": round(remaining, 1), "loss_cooldown_hours": round(remaining / 3600.0, 2), "trade_mode": mode, "execution": "NOT_RUN"})
        _record_chain(final_approved=False, execution_attempted=False, position_opened=False, failed_gate="LOSS_COOLDOWN")
        _legacy.logger.info("ENTRY BLOCKED %s: loss cooldown active for %.0fs mode=%s", symbol, remaining, mode)
        return None
    if not _brain_authority_entry_gate(symbol, candidate_strategy_snapshot, mode):
        trace = runtime.last_entry_diagnostics.setdefault(symbol, {"symbol": symbol})
        failed = trace.get("brain_authority_rejection_reason") or "BRAIN_AUTHORITY"
        _record_chain(final_approved=False, execution_attempted=False, position_opened=False, failed_gate=str(failed))
        return None

    # Snapshot the attribution inputs BEFORE downstream execution. The original
    # open-position path can mutate/reset runtime.last_entry_diagnostics, so
    # rebuilding the chain after execution can otherwise lose the Brain/V2
    # decision that actually authorized this exact entry.
    pre_execution_trace = runtime.last_entry_diagnostics.get(symbol, {}) or {}
    pre_execution_brain = deepcopy(
        (pre_execution_trace.get("brain_authority_by_mode", {}) or {}).get(str(mode).upper())
    )
    pre_execution_v2 = deepcopy(
        (pre_execution_trace.get("entry_v2_shadow_by_mode", {}) or {}).get(str(mode).upper())
    )
    pre_execution_chain = build_entry_decision_chain(
        candidate_strategy_snapshot,
        trade_mode=mode,
        brain_record=pre_execution_brain,
        v2_record=pre_execution_v2,
        final_approved=None,
        execution_attempted=False,
        position_opened=False,
        failed_gate=None,
    )

    # Brain Authority passed (or explicitly bypassed incomplete context).
    _current_trade_mode["value"] = mode
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
        pre_execution_chain["final"] = {
            "approved": True,
            "execution_attempted": True,
            "position_opened": True,
            "failed_gate": None,
        }
        chain = pre_execution_chain
        runtime.last_entry_diagnostics.setdefault(symbol, {})["entry_decision_chain"] = chain
        position.entry_metadata["trade_mode"] = mode
        # Preserve the stop requested at entry before any later protection/trailing
        # logic can mutate position.stop_loss. This is diagnostic-only attribution.
        position.entry_metadata["entry_stop_loss"] = float(stop_loss)
        position.metadata["trade_mode"] = mode
        position.entry_metadata["entry_decision_chain"] = chain
        position.metadata["entry_decision_chain"] = chain
        runtime.repository.update(position)
    else:
        pre_execution_chain["final"] = {
            "approved": False,
            "execution_attempted": True,
            "position_opened": False,
            "failed_gate": "DOWNSTREAM_OPEN_POSITION",
        }
        chain = pre_execution_chain
        runtime.last_entry_diagnostics.setdefault(symbol, {})["entry_decision_chain"] = chain
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
    if opened:
        trace["position_id"] = opened[0].position_id
    else:
        trace.pop("position_id", None)
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


def _reset_entry_diagnostics_for_cycle() -> None:
    """Clear per-symbol entry diagnostics at the start of each market cycle.

    These diagnostics are cycle-scoped observability. Durable Paper outcome evidence
    remains keyed to the committed position, so clearing them cannot erase trade history.
    """
    for symbol in list(runtime.last_entry_diagnostics):
        if not str(symbol).startswith("__"):
            runtime.last_entry_diagnostics.pop(symbol, None)


def _process_market_cycle_with_overlays():
    _reset_entry_diagnostics_for_cycle()
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
    # A previous 418/429 remains diagnostic history after the circuit
    # has reopened. Only report it as an active health state while the
    # local market-data guard is actually blocked.
    if status_code in {418, 429} and blocked:
        _market_health_notify(
            f"BINANCE RATE LIMIT {status_code}",
            f"Path: {last_path}\nRetry in: {retry_in:.0f}s\nData: {data_count}/{symbol_count}",
        )
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

    # Bind diagnostics to the same active manager used by the runtime so
    # manager-controlled Kline refreshes are visible in MARKET-DATA-TRACE.
    _active_market_data_manager = getattr(_legacy, "market_data_manager", None)
    if _active_market_data_manager is not None:
        _legacy._market_data_runtime_trace_bind_manager(_active_market_data_manager)
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


def _paper_engine_health_payload() -> dict:
    heartbeat = runtime.last_entry_diagnostics.get("__paper_loop__", {}) or {}
    payload = _paper_engine_health_snapshot(
        _dual_mode_engine_thread,
        heartbeat,
        max_age_seconds=120.0,
    )
    stream = globals().get("_binance_market_stream")
    if stream is not None and callable(getattr(stream, "snapshot", None)):
        try:
            payload["binance_websocket"] = stream.snapshot()
        except Exception as exc:
            payload["binance_websocket"] = {
                "available": False,
                "mode": "SHADOW_ONLY",
                "error": f"{type(exc).__name__}: {exc}",
            }
    with _binance_rest_ws_compare_lock:
        payload["binance_rest_ws_comparison"] = dict(_binance_rest_ws_last_comparison)
    return payload


@app.get("/health/paper")
def _paper_engine_health():
    payload = _paper_engine_health_payload()
    status_code = 200 if payload["status"] == "ok" else 503
    return jsonify(payload), status_code



_binance_rest_ws_compare_lock = threading.RLock()
_binance_rest_ws_last_comparison: dict[str, object] = {
    "status": "NOT_RUN",
    "symbol": None,
    "interval": None,
    "open_time": None,
    "max_abs_diff": None,
    "fields_match": None,
}
_binance_rest_ws_compare_index = 0
_BINANCE_REST_WS_COMPARE_INTERVALS = ("5m", "15m", "1h", "4h")


def _binance_rest_candles_for_compare(symbol: str, interval: str) -> list[dict]:
    raw = _legacy._binance_get(
        "/api/v3/klines",
        {"symbol": str(symbol).upper(), "interval": str(interval), "limit": 3},
    )
    candles: list[dict] = []
    for row in raw or []:
        if not isinstance(row, (list, tuple)) or len(row) < 7:
            continue
        candles.append(
            {
                "open_time": int(row[0]),
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]),
                "close_time": int(row[6]),
            }
        )
    return candles


def _binance_rest_ws_compare_once(symbol: str, interval: str) -> None:
    global _binance_rest_ws_last_comparison
    stream = globals().get("_binance_market_stream")
    if stream is None or not callable(getattr(stream, "get_latest_kline", None)):
        return

    try:
        rest_candles = _binance_rest_candles_for_compare(symbol, interval)
        ws_candle = stream.get_latest_kline(symbol, interval)
        result = compare_rest_ws_candle(rest_candles, ws_candle)
        result.update(
            {
                "symbol": str(symbol).upper(),
                "interval": str(interval),
                "checked_at": time.time(),
            }
        )
        _legacy.logger.info(
            "[BINANCE-REST-WS-COMPARE] symbol=%s interval=%s status=%s "
            "open_time=%s fields_match=%s max_abs_diff=%s",
            result.get("symbol"),
            result.get("interval"),
            result.get("status"),
            result.get("open_time"),
            result.get("fields_match"),
            result.get("max_abs_diff"),
        )
    except Exception as exc:
        result = {
            "status": "ERROR",
            "symbol": str(symbol).upper(),
            "interval": str(interval),
            "error": f"{type(exc).__name__}: {exc}",
            "checked_at": time.time(),
        }
        _legacy.logger.warning(
            "[BINANCE-REST-WS-COMPARE] symbol=%s interval=%s status=ERROR error=%s",
            symbol,
            interval,
            result["error"],
        )

    with _binance_rest_ws_compare_lock:
        _binance_rest_ws_last_comparison = dict(result)


def _binance_rest_ws_compare_loop() -> None:
    global _binance_rest_ws_compare_index
    compare_symbols = tuple(TRADING_SYMBOLS)
    if not compare_symbols:
        return

    while True:
        try:
            symbol_index = _binance_rest_ws_compare_index // len(_BINANCE_REST_WS_COMPARE_INTERVALS)
            interval_index = _binance_rest_ws_compare_index % len(_BINANCE_REST_WS_COMPARE_INTERVALS)
            symbol = compare_symbols[symbol_index % len(compare_symbols)]
            interval = _BINANCE_REST_WS_COMPARE_INTERVALS[interval_index]
            _binance_rest_ws_compare_once(symbol, interval)
            _binance_rest_ws_compare_index = (_binance_rest_ws_compare_index + 1) % (
                len(compare_symbols) * len(_BINANCE_REST_WS_COMPARE_INTERVALS)
            )
        except Exception:
            _legacy.logger.exception("Binance REST vs WebSocket comparison loop failed")
        time.sleep(60.0)


def _binance_websocket_health_loop() -> None:
    while True:
        try:
            stream = globals().get("_binance_market_stream")
            if stream is not None and callable(getattr(stream, "snapshot", None)):
                snapshot = stream.snapshot()
                _legacy.logger.info(
                    "[BINANCE-WS-HEALTH] connected=%s healthy=%s streams=%s "
                    "kline_coverage=%s/%s ticker_coverage=%s/%s events=%s "
                    "closed_kline=%s reconnects=%s parse_errors=%s last_event_age=%.2f",
                    snapshot.get("connected"),
                    snapshot.get("event_stream_healthy"),
                    snapshot.get("stream_count"),
                    snapshot.get("symbols_with_latest_kline"),
                    snapshot.get("expected_kline_streams"),
                    snapshot.get("tickers_with_latest"),
                    snapshot.get("expected_tickers"),
                    snapshot.get("events_total"),
                    snapshot.get("closed_kline_events"),
                    snapshot.get("reconnects"),
                    snapshot.get("parse_errors"),
                    float(snapshot.get("last_event_age_seconds") or 0.0),
                )
        except Exception:
            _legacy.logger.exception("Binance WebSocket health logger failed")
        time.sleep(60.0)


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
    threading.Thread(
        target=_binance_websocket_health_loop,
        daemon=True,
        name="binance-websocket-health",
    ).start()
    threading.Thread(
        target=_binance_rest_ws_compare_loop,
        daemon=True,
        name="binance-rest-ws-compare",
    ).start()
    _legacy.run_flask()