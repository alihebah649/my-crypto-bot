from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import inspect
import json
import os
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
from core.paper_outcome_analysis import build_paper_outcome_analysis
from core.paper_entry_outcome_forensics import build_linked_entry_outcome_analysis
from core.paper_outcome_report import format_paper_outcome_report
from core.hosted_paper_lab_report import format_hosted_lab_daily_report
from core.paper_market_data_comparison import compare_paper_outcomes_by_market_data_source
from core.source_parity_shadow import build_source_parity_shadow
from core.execution_market_alignment import assess_execution_market_alignment
from core.dual_lane_position_gate import block_for_existing_position
from core.brain_authority import GuardedBrainAuthority
from core.brain_market_regime import derive_market_breadth
from core.paper_precalibration_shadow import (
    TRIAL_NAME as _PRECALIBRATION_SHADOW_TRIAL_NAME,
    build_precalibration_decision_record,
    build_precalibration_shadow_report,
    candidate_identity as _precalibration_candidate_identity,
    entry_risk_snapshot as _precalibration_entry_risk_snapshot,
)
from core.postgres_evidence_store import PostgresEvidenceStore, database_url_from_env
from core.paper_engine_health import snapshot as _paper_engine_health_snapshot
from core.paper_runtime_memory import build_paper_runtime_memory_snapshot
from core.paper_runtime_retention import (
    compact_paper_order_history,
    persist_or_confirm_paper_outcome,
    prune_main_paper_history,
)
from core.paper_entry_gate_summary import build_paper_entry_gate_summary
from core.paper_signal_cycle_summary import build_paper_signal_cycle_summary
from core.paper_entry_funnel import build_entry_funnel_record, build_entry_funnel_report
from core.paper_blocked_entry_shadow import (
    TRIAL_NAME as _BLOCKED_ENTRY_SHADOW_TRIAL_NAME,
    advance_blocked_entry_watch,
    build_blocked_entry_watch,
)
from core.paper_structural_stop_comparison import (
    TRIAL_NAME as _PAPER_STRUCTURAL_STOP_COMPARISON_TRIAL_NAME,
    advance_structural_stop_comparison,
    build_structural_stop_comparison_decision,
    build_structural_stop_comparison_report,
    build_structural_stop_comparison_watch,
)
from core.paper_structural_stop_comparison_runtime import (
    PaperStructuralStopComparisonCoordinator,
)
from engine.entry_v2_capture import capture_summary as _entry_v2_capture_summary
from core.market_health_notifications import should_notify_market_health as _should_notify_market_health
from core.market_health_summary import (
    build_paper_market_health_summary,
    market_data_guard_alert_label,
)
from core.binance_rest_ws_comparison import compare_rest_ws_candle, normalize_rest_candles
from core.hosted_paper_labs import create_hosted_paper_lab_runner
from core.paper_risk_overlay import (
    BTC_RECOVERY_MAX_DRAWDOWN_PERCENT,
    REENTRY_COOLDOWN_SECONDS,
    loss_cooldown_remaining,
    profit_protection_trigger,
    profit_protection_snapshot,
    record_profit_protection_net_floor_shadow,
    strong_bullish_btc_exception,
    btc_recovery_eligible,
    btc_recovery_stop,
    paper_entry_economics,
)

# Cross-venue feature parity and outcome comparisons are intentionally off while
# the project validates isolated venue labs. Main mixed-mode execution alignment
# remains a safety check and is not disabled by this diagnostic toggle.
PAPER_CROSS_VENUE_DIAGNOSTICS_ENABLED = (
    os.getenv("PAPER_CROSS_VENUE_DIAGNOSTICS_ENABLED", "0").strip().lower()
    in {"1", "true", "yes", "on"}
)

# Opt-in experiment: MAIN/Binance SCALP only. Disabled unless explicitly
# enabled in the Render environment; hosted Bybit/OKX labs never pass this flag.
PAPER_MAIN_SCALP_SELLER_PRESSURE_VETO_ENABLED = (
    os.getenv("PAPER_MAIN_SCALP_SELLER_PRESSURE_VETO_ENABLED", "0").strip().lower()
    in {"1", "true", "yes", "on"}
)

_paper_original_process_market_cycle = _legacy.process_market_cycle

_paper_original_notify_closed_positions = _notify_closed_positions
_paper_outcome_evidence_logged_ids: set[str] = set()


# Guarded Brain authority: this is a Paper-only decision gate. A BUY from the
# Brain is only a pre-Risk approval; Risk, Trade Manager and Execution remain
# mandatory downstream authorities.
brain_authority = GuardedBrainAuthority()
_evidence_database_url = database_url_from_env()
_EVIDENCE_NAMESPACE = "" if PAPER_VENUE_MODE == "MIXED" else f"_{PAPER_VENUE_MODE}"
if _evidence_database_url:
    _brain_authority_store = PostgresEvidenceStore(
        _evidence_database_url,
        evidence_type=f"BRAIN_AUTHORITY{_EVIDENCE_NAMESPACE}",
        max_records=50_000,
    )
else:
    _brain_authority_store = BrainShadowCaptureStore(
        Path(getattr(runtime, "persistence_dir", None) or ".") / "brain_shadow" / "authority_captures.jsonl"
    )
# Final dispositions are separate append-only evidence rows in the existing
# paper_evidence table. Keep BRAIN_AUTHORITY immutable; never upsert its rows.
_paper_entry_funnel_store = (
    PostgresEvidenceStore(
        _evidence_database_url,
        evidence_type=f"PAPER_ENTRY_FUNNEL{_EVIDENCE_NAMESPACE}",
        max_records=50_000,
    )
    if _evidence_database_url
    else None
)
_paper_outcome_store = (
    PostgresEvidenceStore(
        _evidence_database_url,
        evidence_type=f"PAPER_OUTCOME{_EVIDENCE_NAMESPACE}",
        max_records=50_000,
    )
    if _evidence_database_url
    else None
)
# Counterfactual-only path tracking for the existing MAIN/SCALP seller-pressure
# Paper veto. It is disabled unless that exact Paper trial is enabled and
# persists only one START and one FINAL event per blocked capture.
_PAPER_BLOCKED_ENTRY_SHADOW_ENABLED = bool(
    PAPER_VENUE_MODE == "MIXED"
    and PAPER_MAIN_SCALP_SELLER_PRESSURE_VETO_ENABLED
    and _evidence_database_url
)
_paper_blocked_entry_shadow_store = (
    PostgresEvidenceStore(
        _evidence_database_url,
        evidence_type="PAPER_BLOCKED_ENTRY_SHADOW",
        max_records=1_000,
    )
    if _PAPER_BLOCKED_ENTRY_SHADOW_ENABLED
    else None
)
_paper_blocked_entry_shadow_lock = threading.RLock()
_paper_blocked_entry_shadow_active_by_symbol: dict[str, dict[str, Any]] = {}


def _restore_blocked_entry_shadow_watches() -> None:
    store = _paper_blocked_entry_shadow_store
    if store is None:
        return
    try:
        records = store.read_all()
        if getattr(store, "last_error", None):
            raise RuntimeError("BLOCKED_ENTRY_SHADOW_RESTORE_READ_FAILED")
        final_capture_ids = {
            str(row.get("source_capture_id") or "").strip()
            for row in records
            if isinstance(row, dict) and row.get("record_type") == "FINAL"
        }
        restored: dict[str, dict[str, Any]] = {}
        for row in records:
            if not isinstance(row, dict) or row.get("record_type") != "START":
                continue
            capture_id = str(row.get("source_capture_id") or "").strip()
            symbol = str(row.get("symbol") or "").upper()
            if (
                not capture_id
                or not symbol
                or capture_id in final_capture_ids
                or str(row.get("status") or "").upper() != "OBSERVING"
            ):
                continue
            previous = restored.get(symbol)
            if previous is None or str(row.get("entry_capture_at_utc") or "") > str(
                previous.get("entry_capture_at_utc") or ""
            ):
                restored[symbol] = dict(row)
        with _paper_blocked_entry_shadow_lock:
            _paper_blocked_entry_shadow_active_by_symbol.update(restored)
        _legacy.logger.warning(
            "[PAPER-BLOCKED-ENTRY-SHADOW] RESTORED active_symbols=%d",
            len(restored),
        )
    except Exception:
        _legacy.logger.exception(
            "[PAPER-BLOCKED-ENTRY-SHADOW] restore failed; no counterfactual result will be inferred"
        )


_restore_blocked_entry_shadow_watches()


# Track only SCALP setups that the previous score formula would have admitted
# but the current formula holds back. A watch begins only after the current
# Brain, its selective Entry v2 veto, and Paper entry economics all pass.
_PAPER_PRECALIBRATION_SHADOW_ENABLED = bool(
    PAPER_VENUE_MODE == "MIXED" and _evidence_database_url
)
_paper_precalibration_shadow_store = (
    PostgresEvidenceStore(
        _evidence_database_url,
        evidence_type="PAPER_SCALP_PRECALIBRATION_SHADOW",
        max_records=1_000,
    )
    if _PAPER_PRECALIBRATION_SHADOW_ENABLED
    else None
)
_paper_precalibration_shadow_lock = threading.RLock()
_paper_precalibration_shadow_active_by_symbol: dict[str, dict[str, Any]] = {}
_paper_precalibration_shadow_seen_candidate_ids: set[str] = set()


def _restore_precalibration_shadow_watches() -> None:
    store = _paper_precalibration_shadow_store
    if store is None:
        return
    try:
        records = store.read_all()
        if getattr(store, "last_error", None):
            raise RuntimeError("PRECALIBRATION_SHADOW_RESTORE_READ_FAILED")
        final_ids = {
            str(row.get("candidate_id") or row.get("source_capture_id") or "").strip()
            for row in records
            if isinstance(row, dict) and row.get("record_type") == "FINAL"
        }
        restored: dict[str, dict[str, Any]] = {}
        seen: set[str] = set()
        for row in records:
            if not isinstance(row, dict):
                continue
            candidate_id = str(
                row.get("candidate_id") or row.get("source_capture_id") or ""
            ).strip()
            if candidate_id:
                seen.add(candidate_id)
            if (
                row.get("record_type") != "START"
                or not candidate_id
                or candidate_id in final_ids
                or str(row.get("status") or "").upper() != "OBSERVING"
            ):
                continue
            symbol = str(row.get("symbol") or "").upper()
            if not symbol:
                continue
            previous = restored.get(symbol)
            if previous is None or str(row.get("entry_capture_at_utc") or "") > str(
                previous.get("entry_capture_at_utc") or ""
            ):
                restored[symbol] = dict(row)
        with _paper_precalibration_shadow_lock:
            _paper_precalibration_shadow_active_by_symbol.update(restored)
            _paper_precalibration_shadow_seen_candidate_ids.update(seen)
        _legacy.logger.warning(
            "[PAPER-PRECALIBRATION-SHADOW] RESTORED active_symbols=%d seen_candidates=%d",
            len(restored),
            len(seen),
        )
    except Exception:
        _legacy.logger.exception(
            "[PAPER-PRECALIBRATION-SHADOW] restore failed; no counterfactual result will be inferred"
        )


_restore_precalibration_shadow_watches()


def _persist_precalibration_decision(record: dict[str, Any]) -> bool:
    store = _paper_precalibration_shadow_store
    if store is None:
        return False
    candidate_id = str(record.get("candidate_id") or "").strip()
    if not candidate_id:
        return False
    payload = dict(record)
    payload.setdefault("schema_version", 1)
    payload.setdefault("trial_name", _PRECALIBRATION_SHADOW_TRIAL_NAME)
    payload["record_type"] = "DECISION"
    payload["record_id"] = f"{candidate_id}:DECISION"
    payload.setdefault("mode", "PAPER_ONLY")
    inserted = store.append(payload)
    if not inserted and getattr(store, "last_error", None):
        raise RuntimeError("PRECALIBRATION_SHADOW_DECISION_PERSIST_FAILED")
    with _paper_precalibration_shadow_lock:
        _paper_precalibration_shadow_seen_candidate_ids.add(candidate_id)
    if inserted:
        _legacy.logger.info(
            "[PAPER-PRECALIBRATION-SHADOW] DECISION %s",
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        )
    return inserted


def _record_precalibration_shadow_candidates() -> None:
    """Evaluate old-formula-only Scalp candidates through current downstream gates."""
    store = _paper_precalibration_shadow_store
    capture_runtime = globals().get("_entry_v2_runtime_capture")
    if store is None or capture_runtime is None:
        return

    scores = getattr(_legacy, "latest_scores", {}) or {}
    if not isinstance(scores, dict):
        return
    market_view = derive_market_breadth(
        scores,
        btc_crashing=bool(_last_btc_guard.get("crashing")),
    )
    fee_rate = float(
        getattr(getattr(runtime, "execution_adapter", None), "fee_rate", 0.001) or 0.001
    )

    for symbol, raw_score in scores.items():
        if not isinstance(raw_score, dict):
            continue
        if (
            str(raw_score.get("scalp_pre_calibration_signal") or "HOLD").upper() != "BUY"
            or str(raw_score.get("scalp_signal") or "HOLD").upper() == "BUY"
        ):
            continue

        normalized = str(symbol or "").upper()
        candidate_id = _precalibration_candidate_identity(
            normalized,
            raw_score.get("scalp_signal_candle_open_time_ms"),
        )
        if not candidate_id:
            continue
        with _paper_precalibration_shadow_lock:
            if candidate_id in _paper_precalibration_shadow_seen_candidate_ids:
                continue
            active = _paper_precalibration_shadow_active_by_symbol.get(normalized)
            active_candidate_id = (
                str(active.get("candidate_id") or active.get("source_capture_id") or "")
                if isinstance(active, dict) else ""
            )
        if active_candidate_id:
            _persist_precalibration_decision({
                "candidate_id": candidate_id,
                "symbol": normalized,
                "trade_mode": "SCALP",
                "signal_candle_open_time_ms": int(raw_score.get("scalp_signal_candle_open_time_ms")),
                "prior_formula_score": float(raw_score.get("scalp_pre_calibration_score") or 0.0),
                "current_formula_score": float(raw_score.get("scalp_score") or 0.0),
                "disposition": "SUPPRESSED_ACTIVE_WATCH",
                "active_candidate_id": active_candidate_id,
                "reason": "ONE_ACTIVE_COUNTERFACTUAL_WATCH_PER_SYMBOL",
            })
            continue

        try:
            close_time_ms = int(float(raw_score.get("scalp_signal_candle_close_time_ms") or 0))
            if close_time_ms <= 0:
                raise ValueError("CLOSED_5M_CANDLE_CLOSE_TIME_UNAVAILABLE")
            captured_at = datetime.fromtimestamp(
                close_time_ms / 1000.0, tz=timezone.utc
            ).isoformat()

            prior_score = float(raw_score.get("scalp_pre_calibration_score") or 0.0)
            candidate_score = dict(raw_score)
            candidate_score.update({
                "trade_mode": "SCALP",
                "signal": "BUY",
                "scalp_signal": "BUY",
                "scalp_score": prior_score,
                "score": prior_score,
            })
            capture = capture_runtime.build_counterfactual_candidate(
                normalized,
                candidate_score,
                trade_mode="SCALP",
                captured_at=captured_at,
            )
            if capture is None:
                raise RuntimeError("ENTRY_V2_COUNTERFACTUAL_CAPTURE_UNAVAILABLE")

            capture_dict = capture.to_dict()
            # Extract the candidate's Entry v2 risk snapshot before preflight
            # reads its stop; this path is diagnostic-only and cannot change
            # the live execution risk or position lifecycle.
            risk = _precalibration_entry_risk_snapshot(capture_dict)
            entry_v2_summary = _entry_v2_capture_summary(capture)
            active_modes = _active_trade_modes(normalized)
            existing_position = "SCALP" in active_modes

            # Match the real Legacy/MAIN Paper gates in order: BTC crash,
            # existing position, valid price/ATR stop, freshness, ticker,
            # cooldown, then Brain and fee-aware entry economics.
            preflight_rejection = None
            preflight_details: dict[str, Any] = {}
            entry_price = float(candidate_score.get("price") or 0.0)
            atr_value = float(candidate_score.get("atr") or 0.0)
            stop_price = risk.get("atr_stop_loss")
            if bool(_last_btc_guard.get("crashing")):
                preflight_rejection = "BTC_CRASH_GUARD"
            elif not existing_position and (entry_price <= 0.0 or atr_value <= 0.0):
                preflight_rejection = "INVALID_ATR_OR_PRICE"
            elif not existing_position and (
                stop_price is None or float(stop_price) <= 0.0
            ):
                preflight_rejection = "INVALID_STOP"
            elif not existing_position:
                freshness = raw_score.get("entry_freshness_5m")
                if not entry_execution_freshness_allowed(freshness, "SCALP"):
                    preflight_rejection = "STALE_ENTRY_DATA"
                    preflight_details["decision_candle_age_seconds"] = (
                        freshness.get("decision_candle_age_seconds")
                        if isinstance(freshness, dict) else None
                    )

            if preflight_rejection is None and not existing_position:
                with _ticker_cache_lock:
                    stale_active = _ticker_cache_stale_active
                    stale_symbols = set(_ticker_stale_symbols)
                if stale_active and (not stale_symbols or normalized in stale_symbols):
                    preflight_rejection = "STALE_TICKER"

            if preflight_rejection is None and not existing_position:
                remaining_cooldown = _loss_cooldown(normalized)
                if remaining_cooldown > 0:
                    preflight_rejection = "LOSS_COOLDOWN"
                    preflight_details["remaining_seconds"] = round(remaining_cooldown, 1)

            if preflight_rejection is not None:
                brain_record = {
                    "brain_action": "NOT_EVALUATED",
                    "brain_reason": preflight_rejection,
                    "allowed": False,
                    "context": {},
                }
            else:
                shadow_brain = GuardedBrainAuthority(brain=brain_authority.brain)
                brain_record = shadow_brain.evaluate_entry(
                    normalized,
                    candidate_score,
                    trade_mode="SCALP",
                    market_regime=market_view.regime,
                    existing_position=existing_position,
                    capture_id=capture.capture_id,
                    entry_v2_shadow=entry_v2_summary,
                    paper_trial_seller_pressure_veto=bool(
                        PAPER_VENUE_MODE == "MIXED"
                        and PAPER_MAIN_SCALP_SELLER_PRESSURE_VETO_ENABLED
                    ),
                ).to_dict()

            target_price = risk.get("target_price")
            target_status = str(risk.get("target_status") or "UNKNOWN").upper()
            reward_risk = risk.get("reward_risk")
            economics = paper_entry_economics(
                trade_mode="SCALP",
                entry_price=entry_price,
                stop_loss=float(stop_price or 0.0),
                target_price=float(target_price) if target_price is not None else None,
                target_status=target_status,
                reward_risk=float(reward_risk) if reward_risk is not None else None,
                fee_rate=fee_rate,
            )

            # MAIN normally consumes Binance-only data. If that ever changes
            # and a candidate comes from Bybit, live execution first rebases
            # entry/stop to a Binance reference. This shadow path does not yet
            # recompute the pivot target against Binance candles, so it must
            # not count that candidate as a comparable price-path watch.
            market_data_rejection = None
            market_data_details: dict[str, Any] = {}
            market_data_source = str(
                candidate_score.get("market_data_source") or "UNKNOWN"
            ).upper()
            if _requires_binance_execution_reference(market_data_source):
                alignment = candidate_score.get("market_data_alignment") or {}
                market_data_details = {
                    "market_data_source": market_data_source,
                    "market_data_alignment": (
                        dict(alignment) if isinstance(alignment, dict) else {}
                    ),
                }
                if not isinstance(alignment, dict) or not bool(alignment.get("eligible")):
                    market_data_rejection = "MARKET_DATA_SOURCE_MISMATCH"
                else:
                    reference_price = float(
                        alignment.get("binance_execution_price", 0.0) or 0.0
                    )
                    risk_distance = entry_price - float(stop_price or 0.0)
                    if (
                        reference_price <= 0.0
                        or risk_distance <= 0.0
                        or reference_price <= risk_distance
                    ):
                        market_data_rejection = "MARKET_DATA_SOURCE_MISMATCH"
                        market_data_details["reason"] = "INVALID_BINANCE_REBASED_ENTRY_OR_STOP"
                    else:
                        market_data_rejection = "MARKET_DATA_REBASE_NOT_MODELED"
                        market_data_details["reason"] = (
                            "BINANCE_ENTRY_STOP_REBASED_BUT_PIVOT_TARGET_NOT_RECOMPUTED_ON_BINANCE_CANDLES"
                        )

            symbol_view = (
                brain_record.get("context", {}).get("symbol_regime", {})
                if isinstance(brain_record.get("context"), dict)
                else {}
            )
            decision = build_precalibration_decision_record(
                candidate_id=candidate_id,
                symbol=normalized,
                candle_open_time_ms=int(raw_score.get("scalp_signal_candle_open_time_ms")),
                captured_at_utc=captured_at,
                prior_score=prior_score,
                current_score=float(raw_score.get("scalp_score") or 0.0),
                entry_price=entry_price,
                stop_price=float(stop_price) if stop_price is not None else None,
                target_price=float(target_price) if target_price is not None else None,
                target_status=target_status,
                reward_risk=float(reward_risk) if reward_risk is not None else None,
                fee_rate_per_side=fee_rate,
                brain_record=brain_record,
                economics=economics,
                entry_v2_capture_id=capture.capture_id,
                entry_v2_decision=str(capture_dict.get("v2_decision", {}).get("decision") or ""),
                entry_v2_failed_gate=str(capture_dict.get("v2_decision", {}).get("failed_gate") or ""),
                existing_position=existing_position,
                market_regime=market_view.regime,
                symbol_regime=str(symbol_view.get("regime") or "UNKNOWN"),
                preflight_rejection=preflight_rejection,
                preflight_details=preflight_details,
                market_data_rejection=market_data_rejection,
                market_data_details=market_data_details,
            )

            if decision["disposition"] == "BRAIN_ECONOMICS_QUALIFIED_WATCH":
                # Reuse the exact Entry v2 stop/target and fee-aware 24-bar
                # path model already used by the seller-pressure counterfactual.
                capture_for_watch = dict(capture_dict)
                capture_for_watch["capture_id"] = candidate_id
                watch = build_blocked_entry_watch(
                    capture_for_watch,
                    fee_rate=fee_rate,
                    blocked_reason="SCALP_PRECALIBRATION_SCORE_DIFFERENCE",
                )
                if str(watch.get("status") or "").upper() != "OBSERVING":
                    decision["disposition"] = "UNMEASURABLE_CONTEXT"
                    decision["measurement_reason"] = str(watch.get("status") or "UNKNOWN")
                    event = {
                        **decision,
                        "record_type": "DECISION",
                        "record_id": f"{candidate_id}:DECISION",
                    }
                    _persist_precalibration_decision(event)
                    continue

                watch.update(decision)
                watch.update({
                    "record_type": "START",
                    "record_id": f"{candidate_id}:START",
                    "candidate_id": candidate_id,
                    "trial_name": _PRECALIBRATION_SHADOW_TRIAL_NAME,
                    "venue": "BINANCE",
                    "venue_mode": "MAIN",
                    "mode": "PAPER_ONLY",
                    "entry_v2_capture_id": capture.capture_id,
                    "entry_v2_decision": capture_dict.get("v2_decision", {}),
                    "brain_shadow_record": brain_record,
                    "economics": economics,
                    "repeat_precalibration_candidates_suppressed": 0,
                    "signal_candle_open_time_ms": int(
                        raw_score.get("scalp_signal_candle_open_time_ms")
                    ),
                    "current_scalp_gate_reasons": list(
                        raw_score.get("scalp_gate_reasons") or []
                    ),
                })
                inserted = store.append(watch)
                if inserted:
                    with _paper_precalibration_shadow_lock:
                        _paper_precalibration_shadow_active_by_symbol[normalized] = dict(watch)
                        _paper_precalibration_shadow_seen_candidate_ids.add(candidate_id)
                    _legacy.logger.info(
                        "[PAPER-PRECALIBRATION-SHADOW] START %s",
                        json.dumps(watch, ensure_ascii=False, separators=(",", ":")),
                    )
                elif getattr(store, "last_error", None):
                    raise RuntimeError("PRECALIBRATION_SHADOW_START_PERSIST_FAILED")
                else:
                    with _paper_precalibration_shadow_lock:
                        _paper_precalibration_shadow_seen_candidate_ids.add(candidate_id)
            else:
                _persist_precalibration_decision(decision)
        except Exception as exc:
            _legacy.logger.exception(
                "[PAPER-PRECALIBRATION-SHADOW] candidate evaluation failed symbol=%s error=%s",
                normalized,
                type(exc).__name__,
            )


def _advance_precalibration_shadow_watches() -> None:
    store = _paper_precalibration_shadow_store
    if store is None:
        return
    stream = globals().get("_binance_market_stream")
    get_history = getattr(stream, "get_kline_history", None)
    if not callable(get_history):
        return

    with _paper_precalibration_shadow_lock:
        watches = list(_paper_precalibration_shadow_active_by_symbol.items())
    for symbol, previous in watches:
        try:
            candles = get_history(symbol, "5m", 60) or []
            updated, _changed = advance_blocked_entry_watch(previous, candles)
        except Exception:
            _legacy.logger.exception(
                "[PAPER-PRECALIBRATION-SHADOW] path update failed symbol=%s",
                symbol,
            )
            continue

        if str(updated.get("status") or "").upper() == "OBSERVING":
            with _paper_precalibration_shadow_lock:
                current = _paper_precalibration_shadow_active_by_symbol.get(symbol)
                if current and current.get("candidate_id") == updated.get("candidate_id"):
                    _paper_precalibration_shadow_active_by_symbol[symbol] = updated
            continue

        final_event = dict(updated)
        candidate_id = str(updated.get("candidate_id") or updated.get("source_capture_id") or "")
        final_event["record_type"] = "FINAL"
        final_event["record_id"] = f"{candidate_id}:FINAL"
        final_event["trial_name"] = _PRECALIBRATION_SHADOW_TRIAL_NAME
        final_event["candidate_id"] = candidate_id
        final_event["venue"] = "BINANCE"
        final_event["venue_mode"] = "MAIN"
        final_event["mode"] = "PAPER_ONLY"
        try:
            inserted = store.append(final_event)
            if not inserted and getattr(store, "last_error", None):
                raise RuntimeError("PRECALIBRATION_SHADOW_FINAL_PERSIST_FAILED")
            with _paper_precalibration_shadow_lock:
                current = _paper_precalibration_shadow_active_by_symbol.get(symbol)
                if current and current.get("candidate_id") == candidate_id:
                    _paper_precalibration_shadow_active_by_symbol.pop(symbol, None)
            _legacy.logger.info(
                "[PAPER-PRECALIBRATION-SHADOW] FINAL %s",
                json.dumps(final_event, ensure_ascii=False, separators=(",", ":")),
            )
        except Exception:
            with _paper_precalibration_shadow_lock:
                _paper_precalibration_shadow_active_by_symbol[symbol] = updated
            _legacy.logger.exception(
                "[PAPER-PRECALIBRATION-SHADOW] final persistence failed symbol=%s",
                symbol,
            )


def _record_blocked_entry_shadow(
    symbol: str,
    capture_id: str | None,
    blocked_reason: str,
) -> None:
    store = _paper_blocked_entry_shadow_store
    normalized = str(symbol or "").upper()
    identity = str(capture_id or "").strip()
    if store is None or not normalized or not identity:
        return

    with _paper_blocked_entry_shadow_lock:
        active = _paper_blocked_entry_shadow_active_by_symbol.get(normalized)
        if active is not None:
            # Do not create repeated virtual positions from every one-minute
            # scan while the same symbol already has an open counterfactual.
            active["repeat_blocked_candidates_suppressed"] = int(
                active.get("repeat_blocked_candidates_suppressed", 0) or 0
            ) + 1
            return

    capture_store = getattr(
        globals().get("_entry_v2_runtime_capture"),
        "capture_store",
        None,
    )
    lookup = getattr(capture_store, "get_by_identity", None)
    if not callable(lookup):
        _legacy.logger.warning(
            "[PAPER-BLOCKED-ENTRY-SHADOW] capture lookup unavailable symbol=%s",
            normalized,
        )
        return
    try:
        capture = lookup(identity)
    except Exception as exc:
        _legacy.logger.warning(
            "[PAPER-BLOCKED-ENTRY-SHADOW] capture lookup failed symbol=%s error=%s",
            normalized,
            type(exc).__name__,
        )
        return
    if not isinstance(capture, dict) or str(capture.get("capture_id") or "") != identity:
        _legacy.logger.warning(
            "[PAPER-BLOCKED-ENTRY-SHADOW] exact capture missing symbol=%s capture_id=%s",
            normalized,
            identity,
        )
        return

    fee_rate = float(
        getattr(getattr(runtime, "execution_adapter", None), "fee_rate", 0.001)
        or 0.001
    )
    watch = build_blocked_entry_watch(
        capture,
        fee_rate=fee_rate,
        blocked_reason=blocked_reason,
    )
    watch["record_type"] = "START"
    watch["record_id"] = f"{identity}:START"
    watch["repeat_blocked_candidates_suppressed"] = 0
    watch["trial_name"] = _BLOCKED_ENTRY_SHADOW_TRIAL_NAME
    watch["venue"] = "BINANCE"
    watch["venue_mode"] = "MAIN"
    try:
        inserted = store.append(watch)
        if not inserted:
            if getattr(store, "last_error", None):
                raise RuntimeError("BLOCKED_ENTRY_SHADOW_START_PERSIST_FAILED")
            # An idempotent duplicate is already durable; restore it into the
            # in-memory watcher only when its start snapshot is measurable.
        if str(watch.get("status")) == "OBSERVING":
            with _paper_blocked_entry_shadow_lock:
                _paper_blocked_entry_shadow_active_by_symbol[normalized] = dict(watch)
        _legacy.logger.warning(
            "[PAPER-BLOCKED-ENTRY-SHADOW] START %s",
            json.dumps(watch, ensure_ascii=False, separators=(",", ":")),
        )
    except Exception:
        _legacy.logger.exception(
            "[PAPER-BLOCKED-ENTRY-SHADOW] start persistence failed symbol=%s capture_id=%s",
            normalized,
            identity,
        )


def _advance_blocked_entry_shadow_watches() -> None:
    store = _paper_blocked_entry_shadow_store
    if store is None:
        return
    stream = globals().get("_binance_market_stream")
    get_history = getattr(stream, "get_kline_history", None)
    if not callable(get_history):
        return

    with _paper_blocked_entry_shadow_lock:
        watches = list(_paper_blocked_entry_shadow_active_by_symbol.items())
    for symbol, previous in watches:
        try:
            candles = get_history(symbol, "5m", 60) or []
            updated, changed = advance_blocked_entry_watch(previous, candles)
        except Exception:
            _legacy.logger.exception(
                "[PAPER-BLOCKED-ENTRY-SHADOW] path update failed symbol=%s",
                symbol,
            )
            continue

        status = str(updated.get("status") or "").upper()
        if status == "OBSERVING":
            if changed:
                with _paper_blocked_entry_shadow_lock:
                    current = _paper_blocked_entry_shadow_active_by_symbol.get(symbol)
                    if current and current.get("source_capture_id") == updated.get("source_capture_id"):
                        _paper_blocked_entry_shadow_active_by_symbol[symbol] = updated
            continue

        final_event = dict(updated)
        final_event["record_type"] = "FINAL"
        final_event["record_id"] = f"{updated.get('source_capture_id')}:FINAL"
        final_event["trial_name"] = _BLOCKED_ENTRY_SHADOW_TRIAL_NAME
        final_event["venue"] = "BINANCE"
        final_event["venue_mode"] = "MAIN"
        try:
            inserted = store.append(final_event)
            if not inserted and getattr(store, "last_error", None):
                raise RuntimeError("BLOCKED_ENTRY_SHADOW_FINAL_PERSIST_FAILED")
            with _paper_blocked_entry_shadow_lock:
                current = _paper_blocked_entry_shadow_active_by_symbol.get(symbol)
                if current and current.get("source_capture_id") == updated.get("source_capture_id"):
                    _paper_blocked_entry_shadow_active_by_symbol.pop(symbol, None)
            _legacy.logger.warning(
                "[PAPER-BLOCKED-ENTRY-SHADOW] FINAL %s",
                json.dumps(final_event, ensure_ascii=False, separators=(",", ":")),
            )
        except Exception:
            # Retain the completed in-memory record and retry the idempotent
            # FINAL append on the next scan. A restart can reconstruct it
            # again from START plus the retained 5m candle history.
            with _paper_blocked_entry_shadow_lock:
                _paper_blocked_entry_shadow_active_by_symbol[symbol] = updated
            _legacy.logger.exception(
                "[PAPER-BLOCKED-ENTRY-SHADOW] final persistence failed symbol=%s",
                symbol,
            )
# The daily report loop lives in shadow_main_legacy.py. That module has its own
# global namespace, so the active durable store must be explicitly bound there;
# otherwise the report silently falls back to process-local runtime positions.
_legacy._paper_outcome_store = _paper_outcome_store

# Extend the existing daily Telegram report with evidence-based aggregates.
# This remains presentation-only and must never become a strategy/execution gate.
_paper_original_daily_report_with_outcomes = _legacy.build_daily_report


def _daily_report_with_outcome_diagnostics(date_key=None):
    base_report = _paper_original_daily_report_with_outcomes(date_key)
    store = _paper_outcome_store
    if store is None or not callable(getattr(store, "read_time_range", None)):
        return base_report

    report_date = date_key or _legacy.datetime.now(_legacy.REPORT_TIMEZONE).strftime("%Y-%m-%d")
    try:
        outcomes = _legacy._durable_paper_outcomes_for_local_date(report_date)
        if getattr(store, "last_error", None):
            _legacy.logger.warning(
                "Daily Paper outcome diagnostics unavailable: durable read failed"
            )
            return base_report + (
                "\\n\\n🔬 تحليل الصفقات المغلقة — PAPER"
                "\\n⚠ تعذر قراءة أدلة النتائج؛ لم تُحسب إحصاءات اليوم."
            )
        analysis = build_paper_outcome_analysis(outcomes)
        return base_report + "\\n\\n" + format_paper_outcome_report(analysis)
    except Exception:
        _legacy.logger.exception("Daily Paper outcome diagnostics formatting failed")
        return base_report + (
            "\\n\\n🔬 تحليل الصفقات المغلقة — PAPER"
            "\\n⚠ تعذر إنشاء التحليل؛ تقرير الصفقات الأساسي ما زال متاحًا."
        )


_legacy.build_daily_report = _daily_report_with_outcome_diagnostics
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
    "PAPER EVIDENCE STORAGE mode=%s backend=%s paper_outcome=%s brain_authority=%s brain_shadow=%s",
    PAPER_VENUE_MODE,
    "POSTGRES" if _evidence_database_url else "LOCAL_JSONL",
    "POSTGRES" if _paper_outcome_store is not None else "LOCAL_LOG_ONLY",
    "POSTGRES" if _evidence_database_url else "LOCAL_JSONL",
    "POSTGRES" if _evidence_database_url else "LOCAL_JSONL",
)


_paper_original_score_symbol = _legacy.score_symbol


def _score_symbol_with_execution_alignment(symbol, ticker, candles_15m, candles_5m):
    result = _paper_original_score_symbol(symbol, ticker, candles_15m, candles_5m)
    if not isinstance(result, dict):
        return result

    source = str(
        result.get("market_data_source")
        or ticker.get("market_data_source", "UNKNOWN")
    ).upper()
    try:
        if source == "BYBIT" and PAPER_VENUE_MODE != "BYBIT_ONLY_LAB":
            stream = getattr(_legacy, "binance_market_stream", None)
            if stream is None:
                result["market_data_alignment"] = {
                    "schema_version": 1,
                    "eligible": False,
                    "status": "MISMATCH",
                    "market_data_source": source,
                    "execution_reference_source": "BINANCE",
                    "reason": "BINANCE_REFERENCE_STREAM_MISSING",
                }
            else:
                stream_snapshot = stream.snapshot()
                result["market_data_alignment"] = assess_execution_market_alignment(
                    market_data_source=source,
                    source_ticker=ticker,
                    source_5m_candles=candles_5m,
                    source_15m_candles=candles_15m,
                    binance_ticker=stream.get_latest_ticker(symbol),
                    binance_5m_closed=stream.get_latest_closed_kline(symbol, "5m"),
                    binance_15m_closed=stream.get_latest_closed_kline(symbol, "15m"),
                    binance_stream_healthy=bool(
                        stream_snapshot.get("event_stream_healthy")
                    ),
                )
                # Diagnostic-only in the mixed architecture: compare the same 5m/15m feature inputs on
                # Bybit and the already-local Binance WS reference. This field
                # never participates in scoring, Brain, risk, or execution.
                if (
                    PAPER_VENUE_MODE != "BYBIT_ONLY_LAB"
                    and PAPER_CROSS_VENUE_DIAGNOSTICS_ENABLED
                ):
                    result["source_parity_shadow"] = build_source_parity_shadow(
                        source_ticker=ticker,
                        source_15m_candles=candles_15m,
                        source_5m_candles=candles_5m,
                        binance_ticker=stream.get_latest_ticker(symbol),
                        binance_15m_candles=stream.get_kline_history(symbol, "15m", 150),
                        binance_5m_candles=stream.get_kline_history(symbol, "5m", 60),
                    )
        else:
            result["market_data_alignment"] = {
                "schema_version": 1,
                "eligible": True,
                "status": "SAME_EXECUTION_VENUE",
                "market_data_source": source,
                "execution_reference_source": source,
                "reason": "SIGNAL_AND_EXECUTION_SAME_VENUE"
                if PAPER_VENUE_MODE == "BYBIT_ONLY_LAB"
                else "SIGNAL_AND_EXECUTION_SAME_VENUE",
            }
    except Exception as exc:
        result["market_data_alignment"] = {
            "schema_version": 1,
            "eligible": False,
            "status": "MISMATCH",
            "market_data_source": source,
            "execution_reference_source": "BINANCE",
            "reason": f"ALIGNMENT_CHECK_ERROR:{type(exc).__name__}",
        }
    return result


_legacy.score_symbol = _score_symbol_with_execution_alignment


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
        entry_v2_shadow=lane_capture,
        paper_trial_seller_pressure_veto=bool(
            PAPER_VENUE_MODE == "MIXED"
            and lane == "SCALP"
            and PAPER_MAIN_SCALP_SELLER_PRESSURE_VETO_ENABLED
        ),
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

    if record.context.get("paper_trial_seller_pressure_veto_applied"):
        if (
            not record.allowed
            and record.brain_reason == "PAPER_TRIAL_MAIN_SCALP_SELLER_PRESSURE"
        ):
            _record_blocked_entry_shadow(
                normalized,
                capture_id,
                record.brain_reason,
            )
        _legacy.logger.warning(
            "[PAPER-TRIAL-MAIN-SCALP-SELLER-PRESSURE] BLOCK symbol=%s score=%.1f regime=%s capture_id=%s",
            normalized,
            record.strategy_score,
            market_view.regime,
            capture_id or "NONE",
        )

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


def _find_evidence_record_for_capture(store, capture_id: str | None) -> dict | None:
    """Resolve one entry-time Brain record without materializing its evidence history."""
    if not capture_id:
        return None
    lookup = getattr(store, "get_by_identity", None)
    if not callable(lookup):
        _legacy.logger.warning(
            "Paper evidence lookup unavailable: store does not support indexed identity reads"
        )
        return None
    try:
        record = lookup(str(capture_id))
    except Exception:
        _legacy.logger.exception("Paper evidence identity lookup failed capture_id=%s", capture_id)
        return None
    if isinstance(record, dict) and str(record.get("capture_id") or "") == str(capture_id):
        return dict(record)
    return None


def _find_brain_authority_record_for_capture(capture_id: str | None) -> dict | None:
    return _find_evidence_record_for_capture(_brain_authority_store, capture_id)


def _find_brain_record_for_capture(capture_id: str | None) -> dict | None:
    return _find_evidence_record_for_capture(brain_shadow_store, capture_id)


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
                if not persist_or_confirm_paper_outcome(_paper_outcome_store, record):
                    _legacy.logger.error(
                        "Paper outcome evidence not confirmed durable position=%s error=%s",
                        position_id,
                        getattr(_paper_outcome_store, "last_error", None),
                    )
                    # Keep this position eligible for retry on the next
                    # notification cycle. Never mark a failed write as logged.
                    continue
            except Exception:
                _legacy.logger.exception(
                    "Paper outcome evidence persistence raised position=%s",
                    position_id,
                )
                continue

        # Without Postgres this is a local log-only deployment; avoid repeating
        # the same log line, but do not prune closed positions without durable
        # outcome evidence.
        _paper_outcome_evidence_logged_ids.add(position_id)
        emitted += 1
    return emitted


def _notify_closed_positions_with_evidence() -> int:
    _emit_paper_outcome_evidence()
    sent = _paper_original_notify_closed_positions()
    try:
        removed_positions = prune_main_paper_history(
            runtime,
            _paper_outcome_store,
            _paper_outcome_evidence_logged_ids,
        )
        removed_orders = compact_paper_order_history(runtime.execution_adapter)
        if removed_positions or removed_orders:
            _legacy.logger.info(
                "PAPER RUNTIME RETENTION pruned_positions=%s compacted_order_results=%s "
                "position_window_days=40 order_history_limit=1000",
                len(removed_positions),
                removed_orders,
            )
    except Exception:
        # Retention is maintenance only. It must not interrupt the Paper loop
        # or suppress close notifications if a maintenance operation fails.
        _legacy.logger.exception("Paper runtime retention maintenance failed")
    return sent


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


def _requires_binance_execution_reference(market_data_source: str) -> bool:
    """Only MIXED mode routes Bybit-generated signals through Binance reference checks."""
    return (
        str(market_data_source or "").upper() == "BYBIT"
        and PAPER_VENUE_MODE == "MIXED"
    )
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
_ticker_stale_symbols: set[str] = set()


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
    global _ticker_cache, _ticker_cache_hits, _ticker_cache_misses, _ticker_cache_stale_uses
    global _ticker_cache_stale_active, _ticker_stale_symbols

    now = time.time()
    expected_symbols = {str(symbol).upper() for symbol in TRADING_SYMBOLS}
    # Historical staggered ticker wiring retained for compatibility/documentation:
    # manager.refresh_ticker_group(_fetch_ticker_group_from_binance, now=now)
    # data = manager.merged_ticker_snapshot()
    with _ticker_cache_lock:
        cached = _ticker_cache
        if cached is not None and now - cached[0] < _TICKER_CACHE_TTL:
            _ticker_cache_hits += 1
            _ticker_cache_stale_active = False
            return cached[1]

    _ticker_cache_misses += 1
    # Use the active runtime ticker provider first. In Paper mode this is the
    # Binance WebSocket-authoritative adapter installed by BinanceMarketStream,
    # with REST retained only as its bounded cold-start/stale fallback. Calling
    # _guarded_fetch_24h_tickers() directly here bypasses that adapter and turns
    # every cache expiry into an unnecessary Binance REST ticker request.
    fresh_data = _paper_original_24h_tickers(TRADING_SYMBOLS)
    if fresh_data:
        with _ticker_cache_lock:
            previous = dict(_ticker_cache[1]) if _ticker_cache is not None else {}
            merged = dict(previous)
            merged.update(fresh_data)
            _ticker_cache = (time.time(), merged)
            _ticker_stale_symbols = expected_symbols - set(fresh_data)
            _ticker_cache_stale_active = bool(_ticker_stale_symbols)
            if not _ticker_stale_symbols:
                _ticker_cache_stale_active = False
        return merged

    # Both venues may temporarily be unavailable. Reuse the bounded old snapshot
    # exactly as before, but mark every symbol stale so new entries are blocked.
    with _ticker_cache_lock:
        cached = _ticker_cache
        if cached is not None and now - cached[0] < _TICKER_STALE_MAX_AGE:
            _ticker_cache_stale_uses += 1
            _ticker_cache_stale_active = True
            _ticker_stale_symbols = set(expected_symbols)
            return cached[1]
        _ticker_cache_stale_active = False
        _ticker_stale_symbols = set(expected_symbols)
    return {}


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


def _persist_entry_funnel_outcome_impl(
    symbol: str,
    mode: str,
    final_status: str,
    *,
    failed_gate: str | None = None,
    strategy_snapshot: dict | None = None,
    execution_attempted: bool = False,
    position_opened: bool = False,
    details: dict | None = None,
    brain_record_snapshot: dict | None = None,
    v2_capture_snapshot: dict | None = None,
) -> bool:
    """Append final Paper disposition without mutating the original Brain evidence."""
    normalized = str(symbol or "").upper()
    lane = str(mode or "UNKNOWN").upper()
    trace = runtime.last_entry_diagnostics.get(normalized, {}) or {}
    authority_by_mode = trace.get("brain_authority_by_mode", {}) or {}
    authority = brain_record_snapshot if isinstance(brain_record_snapshot, dict) else authority_by_mode.get(lane)
    authority = authority if isinstance(authority, dict) else None
    v2_by_mode = trace.get("entry_v2_shadow_by_mode", {}) or {}
    v2_capture = v2_capture_snapshot if isinstance(v2_capture_snapshot, dict) else (v2_by_mode.get(lane, {}) or {})
    current_v2_capture_id = str(v2_capture.get("capture_id") or "")
    authority_capture_id = str((authority or {}).get("capture_id") or "")
    # A pre-Brain rejection can happen before the current cycle refreshes its
    # Brain record. Never attach that rejection to the previous cycle's capture.
    if current_v2_capture_id and authority_capture_id and current_v2_capture_id != authority_capture_id:
        authority = None
        authority_capture_id = ""
    capture_id = authority_capture_id or current_v2_capture_id
    if not capture_id:
        return False

    snapshot = strategy_snapshot if isinstance(strategy_snapshot, dict) else {}
    captured_at = v2_capture.get("captured_at")
    context = (authority or {}).get("context", {})
    nested_v2 = context.get("entry_v2_shadow", {}) if isinstance(context, dict) else {}
    if not captured_at and isinstance(nested_v2, dict):
        captured_at = nested_v2.get("captured_at")
    score_key = "scalp_score" if lane == "SCALP" else "swing_score"
    strategy_score = snapshot.get(score_key, snapshot.get("score"))
    market_view = trace.get("brain_authority_market_regime", {})
    record = build_entry_funnel_record(
        authority,
        symbol=normalized,
        trade_mode=lane,
        capture_id=str(capture_id),
        captured_at=str(captured_at or ""),
        strategy_action=str(
            snapshot.get("scalp_signal" if lane == "SCALP" else "swing_signal")
            or snapshot.get("signal")
            or "BUY"
        ),
        strategy_score=float(strategy_score) if strategy_score is not None else None,
        final_status=final_status,
        failed_gate=failed_gate,
        execution_attempted=execution_attempted,
        position_opened=position_opened,
        details={
            "market_regime": market_view.get("regime") if isinstance(market_view, dict) else None,
            **(details or {}),
        },
        recorded_at_utc=datetime.now(timezone.utc).isoformat(),
    )
    if not record:
        return False

    store = _paper_entry_funnel_store
    append = getattr(store, "append", None)
    if not callable(append):
        _legacy.logger.warning(
            "PAPER ENTRY FUNNEL persistence unavailable symbol=%s mode=%s capture_id=%s",
            normalized,
            lane,
            capture_id,
        )
        return False
    if not append(record):
        # append() is intentionally idempotent. A duplicate is success only
        # when the durable final disposition already matches this exact capture.
        lookup = getattr(store, "get_by_identity", None)
        existing = lookup(str(capture_id)) if callable(lookup) else None
        existing_final = existing.get("final_decision") if isinstance(existing, dict) else {}
        expected_final = record.get("final_decision") or {}
        existing_stable = {
            key: value for key, value in (existing_final or {}).items()
            if key != "recorded_at_utc"
        } if isinstance(existing_final, dict) else {}
        expected_stable = {
            key: value for key, value in expected_final.items()
            if key != "recorded_at_utc"
        } if isinstance(expected_final, dict) else {}
        if (
            isinstance(existing, dict)
            and str(existing.get("capture_id") or "") == str(capture_id)
            and existing_stable == expected_stable
        ):
            return True
        _legacy.logger.warning(
            "PAPER ENTRY FUNNEL append failed symbol=%s mode=%s capture_id=%s error=%s",
            normalized,
            lane,
            capture_id,
            getattr(store, "last_error", None),
        )
        return False
    return True


def _persist_entry_funnel_outcome(*args, **kwargs) -> bool:
    """Best-effort diagnostics must never interrupt the Paper entry lifecycle."""
    try:
        return _persist_entry_funnel_outcome_impl(*args, **kwargs)
    except Exception as exc:
        _legacy.logger.warning(
            "PAPER ENTRY FUNNEL diagnostics skipped after error=%s",
            type(exc).__name__,
        )
        return False


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
        _persist_entry_funnel_outcome(symbol, mode, "REJECTED_STALE_ENTRY_DATA", failed_gate="STALE_ENTRY_DATA", strategy_snapshot=candidate_strategy_snapshot, details={"decision_candle_age_seconds": (freshness or {}).get("decision_candle_age_seconds")})
        _legacy.logger.info(
            "ENTRY BLOCKED %s: stale 5m decision data mode=%s age=%ss",
            symbol,
            mode,
            (freshness or {}).get("decision_candle_age_seconds"),
        )
        return None
    with _ticker_cache_lock:
        stale_active = _ticker_cache_stale_active
        stale_symbols = set(_ticker_stale_symbols)
    if stale_active and (not stale_symbols or symbol.upper() in stale_symbols):
        trace = runtime.last_entry_diagnostics.setdefault(symbol, {"symbol": symbol})
        trace.update({"result": "REJECTED_STALE_TICKER", "ticker_stale_active": True, "trade_mode": mode, "execution": "NOT_RUN"})
        _record_chain(final_approved=False, execution_attempted=False, position_opened=False, failed_gate="STALE_TICKER")
        _persist_entry_funnel_outcome(symbol, mode, "REJECTED_STALE_TICKER", failed_gate="STALE_TICKER", strategy_snapshot=candidate_strategy_snapshot)
        _legacy.logger.info("ENTRY BLOCKED %s: stale ticker snapshot active mode=%s", symbol, mode)
        return None
    remaining = _loss_cooldown(symbol)
    if remaining > 0:
        trace = runtime.last_entry_diagnostics.setdefault(symbol, {"symbol": symbol})
        trace.update({"result": "REJECTED_LOSS_COOLDOWN", "loss_cooldown_seconds": round(remaining, 1), "loss_cooldown_hours": round(remaining / 3600.0, 2), "trade_mode": mode, "execution": "NOT_RUN"})
        _record_chain(final_approved=False, execution_attempted=False, position_opened=False, failed_gate="LOSS_COOLDOWN")
        _persist_entry_funnel_outcome(symbol, mode, "REJECTED_LOSS_COOLDOWN", failed_gate="LOSS_COOLDOWN", strategy_snapshot=candidate_strategy_snapshot, details={"remaining_seconds": round(remaining, 1)})
        _legacy.logger.info("ENTRY BLOCKED %s: loss cooldown active for %.0fs mode=%s", symbol, remaining, mode)
        return None
    if not _brain_authority_entry_gate(symbol, candidate_strategy_snapshot, mode):
        trace = runtime.last_entry_diagnostics.setdefault(symbol, {"symbol": symbol})
        failed = trace.get("brain_authority_rejection_reason") or "BRAIN_AUTHORITY"
        _record_chain(final_approved=False, execution_attempted=False, position_opened=False, failed_gate=str(failed))
        _persist_entry_funnel_outcome(symbol, mode, "REJECTED_BRAIN_AUTHORITY", failed_gate=str(failed), strategy_snapshot=candidate_strategy_snapshot)
        return None

    # Entry v2 remains advisory, but live Paper execution must not knowingly
    # enter a candidate whose current structural target cannot cover the
    # documented RR and round-trip fee floor.
    trace = runtime.last_entry_diagnostics.setdefault(symbol, {"symbol": symbol})
    lane_capture = (
        (trace.get("entry_v2_shadow_by_mode", {}) or {}).get(str(mode).upper(), {})
        or {}
    )
    fee_rate = float(
        getattr(getattr(runtime, "execution_adapter", None), "fee_rate", 0.001)
        or 0.001
    )
    economics = paper_entry_economics(
        trade_mode=mode,
        entry_price=float(entry_price),
        stop_loss=float(stop_loss),
        target_price=lane_capture.get("target_price"),
        target_status=lane_capture.get("target_status"),
        reward_risk=lane_capture.get("reward_risk"),
        fee_rate=fee_rate,
    )
    trace["entry_economics"] = economics
    if not economics.get("approved", True):
        failed = f"PAPER_ENTRY_ECONOMICS:{economics.get('reason', 'REJECTED')}"
        trace.update({
            "result": "REJECTED_ENTRY_ECONOMICS",
            "trade_mode": mode,
            "execution": "NOT_RUN",
            "entry_economics_rejection_reason": economics.get("reason"),
        })
        _record_chain(
            final_approved=False,
            execution_attempted=False,
            position_opened=False,
            failed_gate=failed,
        )
        _persist_entry_funnel_outcome(symbol, mode, "REJECTED_ENTRY_ECONOMICS", failed_gate=str(economics.get("reason") or "ENTRY_ECONOMICS"), strategy_snapshot=candidate_strategy_snapshot, details={"reward_risk": economics.get("reward_risk"), "required_reward_risk": economics.get("required_reward_risk"), "net_reward_percent": economics.get("net_reward_percent")})
        _legacy.logger.info(
            "ENTRY BLOCKED %s: paper entry economics mode=%s rr=%s net_reward=%s reason=%s",
            symbol,
            mode,
            economics.get("reward_risk"),
            economics.get("net_reward_percent"),
            economics.get("reason"),
        )
        return None

    market_data_source = str(
        candidate_strategy_snapshot.get("market_data_source", "UNKNOWN")
    ).upper()
    market_data_alignment = candidate_strategy_snapshot.get("market_data_alignment") or {}
    execution_price = float(entry_price)
    execution_stop_loss = float(stop_loss)

    if _requires_binance_execution_reference(market_data_source):
        if not isinstance(market_data_alignment, dict) or not bool(
            market_data_alignment.get("eligible")
        ):
            reason = str(
                market_data_alignment.get("reason")
                if isinstance(market_data_alignment, dict)
                else "MARKET_DATA_ALIGNMENT_UNAVAILABLE"
            )
            trace = runtime.last_entry_diagnostics.setdefault(symbol, {"symbol": symbol})
            trace.update({
                "result": "REJECTED_MARKET_DATA_SOURCE_MISMATCH",
                "trade_mode": mode,
                "execution": "NOT_RUN",
                "market_data_source": market_data_source,
                "market_data_alignment": market_data_alignment,
                "market_data_alignment_reason": reason,
            })
            _record_chain(
                final_approved=False,
                execution_attempted=False,
                position_opened=False,
                failed_gate="MARKET_DATA_SOURCE_MISMATCH",
            )
            _persist_entry_funnel_outcome(symbol, mode, "REJECTED_MARKET_DATA_SOURCE_MISMATCH", failed_gate="MARKET_DATA_SOURCE_MISMATCH", strategy_snapshot=candidate_strategy_snapshot, details={"market_data_alignment": market_data_alignment})
            _legacy.logger.info(
                "ENTRY BLOCKED %s: Bybit signal not aligned with Binance execution reference reason=%s mode=%s",
                symbol,
                reason,
                mode,
            )
            return None

        execution_reference_price = float(
            market_data_alignment.get("binance_execution_price", 0.0) or 0.0
        )
        if execution_reference_price <= 0:
            trace = runtime.last_entry_diagnostics.setdefault(symbol, {"symbol": symbol})
            trace.update({
                "result": "REJECTED_MARKET_DATA_SOURCE_MISMATCH",
                "trade_mode": mode,
                "execution": "NOT_RUN",
                "market_data_source": market_data_source,
                "market_data_alignment": market_data_alignment,
                "market_data_alignment_reason": "INVALID_BINANCE_EXECUTION_PRICE",
            })
            _record_chain(
                final_approved=False,
                execution_attempted=False,
                position_opened=False,
                failed_gate="MARKET_DATA_SOURCE_MISMATCH",
            )
            _persist_entry_funnel_outcome(symbol, mode, "REJECTED_MARKET_DATA_SOURCE_MISMATCH", failed_gate="MARKET_DATA_SOURCE_MISMATCH", strategy_snapshot=candidate_strategy_snapshot, details={"market_data_alignment": market_data_alignment})
            return None

        risk_distance = float(entry_price) - float(stop_loss)
        if risk_distance <= 0 or execution_reference_price <= risk_distance:
            trace = runtime.last_entry_diagnostics.setdefault(symbol, {"symbol": symbol})
            trace.update({
                "result": "REJECTED_MARKET_DATA_SOURCE_MISMATCH",
                "trade_mode": mode,
                "execution": "NOT_RUN",
                "market_data_source": market_data_source,
                "market_data_alignment": market_data_alignment,
                "market_data_alignment_reason": "INVALID_REBASED_STOP",
            })
            _record_chain(
                final_approved=False,
                execution_attempted=False,
                position_opened=False,
                failed_gate="MARKET_DATA_SOURCE_MISMATCH",
            )
            _persist_entry_funnel_outcome(symbol, mode, "REJECTED_MARKET_DATA_SOURCE_MISMATCH", failed_gate="MARKET_DATA_SOURCE_MISMATCH", strategy_snapshot=candidate_strategy_snapshot, details={"market_data_alignment": market_data_alignment})
            return None

        execution_price = execution_reference_price
        execution_stop_loss = execution_reference_price - risk_distance

    trace = runtime.last_entry_diagnostics.setdefault(symbol, {"symbol": symbol})
    trace["market_data_source"] = market_data_source
    trace["execution_market_data_source"] = market_data_source
    trace["market_data_alignment"] = market_data_alignment
    trace["signal_price"] = float(entry_price)
    trace["execution_reference_price"] = float(execution_price)
    trace["signal_stop_loss"] = float(stop_loss)
    trace["execution_stop_loss"] = float(execution_stop_loss)

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
            execution_price,
            execution_stop_loss,
            trade_mode=mode,
            strategy_snapshot=candidate_strategy_snapshot,
            strategy_snapshot_captured_at=candidate_snapshot_captured_at,
        )
    else:
        position = _original_runtime_open_position(
            symbol,
            execution_price,
            execution_stop_loss,
            trade_mode=mode,
        )

    downstream_trace = runtime.last_entry_diagnostics.get(symbol, {}) or {}
    if position is None:
        _legacy.logger.warning(
            "DOWNSTREAM ENTRY RESULT %s mode=%s risk_gateway=%s risk_reason=%s facade=%s execution=%s result=%s",
            symbol,
            mode,
            downstream_trace.get("risk_gateway"),
            downstream_trace.get("risk_reason"),
            downstream_trace.get("facade"),
            downstream_trace.get("execution"),
            downstream_trace.get("result"),
        )

    if position is not None:
        pre_execution_chain["final"] = {
            "approved": True,
            "execution_attempted": True,
            "position_opened": True,
            "failed_gate": None,
        }
        chain = pre_execution_chain
        runtime.last_entry_diagnostics.setdefault(symbol, {})["entry_decision_chain"] = chain
        # Freeze the exact market-data configuration at entry, so outcome
        # cohorts remain valid after a later deploy changes the active policy.
        venue_mode = str(PAPER_VENUE_MODE).strip().upper()
        market_data_policy = market_data_policy_label(
            PAPER_VENUE_MODE,
            main_binance_only=_PAPER_MAIN_BINANCE_ONLY,
        )
        position.entry_metadata["trade_mode"] = mode
        position.entry_metadata["venue_mode"] = venue_mode
        position.entry_metadata["market_data_policy"] = market_data_policy
        position.entry_metadata["market_data_source"] = market_data_source
        position.entry_metadata["execution_market_data_source"] = (
            market_data_source if PAPER_VENUE_MODE != "MIXED" else "BINANCE"
        )
        position.entry_metadata["signal_entry_price"] = float(entry_price)
        position.entry_metadata["execution_reference_price"] = float(execution_price)
        position.entry_metadata["market_data_alignment"] = deepcopy(market_data_alignment)
        # Preserve the stop requested at entry before any later protection/trailing
        # logic can mutate position.stop_loss. This is diagnostic-only attribution.
        position.entry_metadata["entry_stop_loss"] = float(execution_stop_loss)
        position.entry_metadata["entry_economics"] = deepcopy(economics)
        position.metadata["entry_economics"] = deepcopy(economics)
        position.metadata["trade_mode"] = mode
        position.metadata["venue_mode"] = venue_mode
        position.metadata["market_data_policy"] = market_data_policy
        position.metadata["market_data_source"] = market_data_source
        position.metadata["execution_market_data_source"] = (
            market_data_source if PAPER_VENUE_MODE != "MIXED" else "BINANCE"
        )
        position.entry_metadata["entry_decision_chain"] = chain
        position.metadata["entry_decision_chain"] = chain
        runtime.repository.update(position)
        _persist_entry_funnel_outcome(symbol, mode, "POSITION_COMMITTED", strategy_snapshot=candidate_strategy_snapshot, execution_attempted=True, position_opened=True, details={"position_id": str(getattr(position, "position_id", "") or ""), "execution_price": float(execution_price)}, brain_record_snapshot=pre_execution_brain, v2_capture_snapshot=pre_execution_v2)
    else:
        pre_execution_chain["final"] = {
            "approved": False,
            "execution_attempted": True,
            "position_opened": False,
            "failed_gate": "DOWNSTREAM_OPEN_POSITION",
        }
        chain = pre_execution_chain
        runtime.last_entry_diagnostics.setdefault(symbol, {})["entry_decision_chain"] = chain
        downstream_gate = str(downstream_trace.get("risk_reason") or downstream_trace.get("result") or "DOWNSTREAM_OPEN_POSITION")
        _persist_entry_funnel_outcome(symbol, mode, "DOWNSTREAM_ENTRY_REJECTED", failed_gate=downstream_gate, strategy_snapshot=candidate_strategy_snapshot, execution_attempted=True, details={"risk_gateway": downstream_trace.get("risk_gateway"), "risk_reason": downstream_trace.get("risk_reason"), "facade": downstream_trace.get("facade"), "execution": downstream_trace.get("execution"), "result": downstream_trace.get("result")}, brain_record_snapshot=pre_execution_brain, v2_capture_snapshot=pre_execution_v2)
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
    dual_lane_candidate = len(requested_modes) == 2
    dual_lane_resolution = None
    dual_lane_duplicate_blocked = False
    if dual_lane_candidate:
        selected_mode = str(score.get("trade_mode", "") or "").upper()
        if selected_mode not in {"SCALP", "SWING"}:
            scalp_score = float(score.get("scalp_score", -1.0) or -1.0)
            swing_score = float(score.get("swing_score", -1.0) or -1.0)
            selected_mode = "SCALP" if scalp_score >= swing_score else "SWING"
        dual_lane_resolution = selected_mode
        # SCALP and SWING can be independently requested by the strategy, but
        # a simultaneous BUY is one underlying observation. Never stack both
        # lanes from that same signal.
        if active_modes:
            dual_lane_duplicate_blocked = True
            requested_modes = []
        else:
            requested_modes = [selected_mode]
    if dual_lane_duplicate_blocked:
        for blocked_mode in modes:
            _persist_entry_funnel_outcome(symbol, blocked_mode, "SKIPPED_EXISTING_POSITION", failed_gate="SAME_UNDERLYING_SIGNAL_ALREADY_ACTIVE", strategy_snapshot=score, details={"active_modes": sorted(active_modes)})
    skipped_existing = []
    opened = []
    for mode in requested_modes:
        if mode in active_modes:
            skipped_existing.append(mode)
            _persist_entry_funnel_outcome(symbol, mode, "SKIPPED_EXISTING_POSITION", failed_gate="ACTIVE_POSITION_SAME_MODE", strategy_snapshot=score)
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
    trace["dual_lane_candidate"] = dual_lane_candidate
    trace["dual_lane_resolution"] = dual_lane_resolution
    trace["dual_lane_duplicate_blocked"] = dual_lane_duplicate_blocked
    trace["dual_lane_duplicate_reason"] = (
        "SAME_UNDERLYING_SIGNAL_ALREADY_ACTIVE" if dual_lane_duplicate_blocked else None
    )
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
from engine.entry_v2_shadow_report import build_entry_v2_shadow_report_endpoint_payload as _build_entry_v2_shadow_report_endpoint_payload

_entry_v2_runtime_capture = _install_entry_v2_runtime_capture(
    legacy=_legacy,
    runtime=runtime,
    mtf_candles=_mtf_candles,
    trading_symbols=TRADING_SYMBOLS,
    btc_guard_provider=lambda: _last_btc_guard,
)


# Paired, non-authoritative comparison of the entry-time ATR and structural
# stops. Each isolated Render Paper service uses only its own venue stream.
_PAPER_STRUCTURAL_STOP_COMPARISON_VENUES = {
    # MAIN is the persisted venue_mode on restored watches. Keep it as an
    # explicit alias so the coordinator resumes against Binance after restart.
    "MAIN": ("BINANCE", "_binance_market_stream", "MAIN"),
    "MIXED": ("BINANCE", "_binance_market_stream", "MAIN"),
    "BINANCE_ONLY_LAB": ("BINANCE", "_binance_market_stream", "BINANCE_ONLY_LAB"),
    "BYBIT_ONLY_LAB": ("BYBIT", "_bybit_market_stream", "BYBIT_ONLY_LAB"),
    "OKX_ONLY_LAB": ("OKX", "_okx_market_stream", "OKX_ONLY_LAB"),
}
_PAPER_STRUCTURAL_STOP_COMPARISON_ENABLED = bool(
    _evidence_database_url
    and PAPER_VENUE_MODE in _PAPER_STRUCTURAL_STOP_COMPARISON_VENUES
)
_paper_structural_stop_comparison_store = (
    PostgresEvidenceStore(
        _evidence_database_url,
        evidence_type=f"PAPER_STRUCTURAL_STOP_COMPARISON{_EVIDENCE_NAMESPACE}",
        max_records=20_000,
    )
    if _PAPER_STRUCTURAL_STOP_COMPARISON_ENABLED
    else None
)
_paper_structural_stop_comparison_lock = threading.RLock()
_paper_structural_stop_comparison_active: dict[str, dict[str, Any]] = {}
_paper_structural_stop_comparison_missing_stream_warned: set[str] = set()
_hosted_paper_structural_stop_coordinator = PaperStructuralStopComparisonCoordinator(
    logger=_legacy.logger
)


def _attach_hosted_paper_structural_stop_comparison(runner: Any) -> None:
    """Attach separate stop monitors to each hosted venue's own Paper account."""
    if runner is None or not getattr(runner, "enabled", False) or getattr(runner, "monitor_only", True):
        return
    for venue, lab in getattr(runner, "labs", {}).items():
        venue_name = str(venue or "").upper()
        context_key = f"HOSTED_{venue_name}"
        store = PostgresEvidenceStore(
            _evidence_database_url,
            evidence_type=f"PAPER_STRUCTURAL_STOP_COMPARISON_{venue_name}_HOSTED_LAB",
            max_records=20_000,
        )
        _hosted_paper_structural_stop_coordinator.add_context(
            context_key=context_key,
            venue=venue_name,
            venue_mode=f"{venue_name}_HOSTED_PAPER_LAB",
            repository=lab.repository,
            stream=lab.stream,
            runtime=lab.runtime,
            evidence_store=store,
            entry_capture_store=lab.entry_captures,
            restore=True,
        )

        original_persist = lab._persist_candidate_capture

        def _persist_candidate_capture_with_stop_shadow(
            capture,
            *,
            _original=original_persist,
            _lab=lab,
            _context_key=context_key,
            **kwargs,
        ):
            result = _original(capture, **kwargs)
            if str(kwargs.get("decision") or "").upper() == "PAPER_POSITION_OPENED":
                position_id = str(kwargs.get("position_id") or "").strip()
                getter = getattr(_lab.repository, "get", None)
                position = getter(position_id) if position_id and callable(getter) else None
                if position is not None:
                    try:
                        _hosted_paper_structural_stop_coordinator.register_start(
                            _context_key,
                            position,
                            capture.to_dict(),
                        )
                    except Exception:
                        _legacy.logger.exception(
                            "[PAPER-STRUCTURAL-STOP-COMPARISON] hosted START observer failed venue=%s position_id=%s",
                            _lab.venue,
                            position_id,
                        )
            return result

        lab._persist_candidate_capture = _persist_candidate_capture_with_stop_shadow
        _legacy.logger.info(
            "[PAPER-STRUCTURAL-STOP-COMPARISON] hosted context attached venue=%s entries_enabled=True",
            venue_name,
        )


def _seed_existing_hosted_paper_structural_stop_positions() -> None:
    """Backfill only still-open hosted positions with exact capture and local 5m coverage."""
    runner = globals().get("_hosted_paper_lab_runner")
    if runner is None or not getattr(runner, "enabled", False) or getattr(runner, "monitor_only", True):
        return
    for venue, lab in getattr(runner, "labs", {}).items():
        if not bool(getattr(lab, "universe_ready", False)):
            continue
        context_key = f"HOSTED_{str(venue or '').upper()}"
        try:
            _hosted_paper_structural_stop_coordinator.seed_existing_open_positions(context_key)
        except Exception:
            _legacy.logger.exception(
                "[PAPER-STRUCTURAL-STOP-COMPARISON] existing hosted position seed failed venue=%s",
                venue,
            )


def _structural_stop_comparison_stream(venue_mode: str | None = None):
    mode = str(venue_mode or PAPER_VENUE_MODE or "UNKNOWN").upper()
    spec = _PAPER_STRUCTURAL_STOP_COMPARISON_VENUES.get(mode)
    if spec is None:
        return "UNKNOWN", None, mode
    venue, stream_name, report_mode = spec
    return venue, globals().get(stream_name), report_mode


def _restore_structural_stop_comparison_watches() -> None:
    store = _paper_structural_stop_comparison_store
    if store is None:
        return
    try:
        records = store.read_all()
        if getattr(store, "last_error", None):
            raise RuntimeError("STRUCTURAL_STOP_COMPARISON_RESTORE_READ_FAILED")
        final_ids = {
            str(row.get("position_id") or "").strip()
            for row in records
            if isinstance(row, dict) and row.get("record_type") == "FINAL"
        }
        restored: dict[str, dict[str, Any]] = {}
        for row in records:
            if not isinstance(row, dict) or row.get("record_type") != "START":
                continue
            position_id = str(row.get("position_id") or "").strip()
            if (
                not position_id
                or position_id in final_ids
                or str(row.get("status") or "").upper() not in {"OBSERVING", "COMPLETE"}
            ):
                continue
            restored[position_id] = dict(row)
        with _paper_structural_stop_comparison_lock:
            _paper_structural_stop_comparison_active.update(restored)
        _legacy.logger.info(
            "[PAPER-STRUCTURAL-STOP-COMPARISON] RESTORED active_positions=%d venue_mode=%s",
            len(restored),
            PAPER_VENUE_MODE,
        )
    except Exception:
        _legacy.logger.exception(
            "[PAPER-STRUCTURAL-STOP-COMPARISON] restore failed; no missing price path will be inferred"
        )


_restore_structural_stop_comparison_watches()


def _record_structural_stop_comparison_decision(
    position: Any,
    *,
    source_capture_id: str,
    venue: str,
    venue_mode: str,
    reason: str,
) -> None:
    store = _paper_structural_stop_comparison_store
    if store is None:
        return
    position_id = str(getattr(position, "position_id", "") or "").strip()
    if not position_id:
        return
    decision = build_structural_stop_comparison_decision(
        position,
        source_capture_id=source_capture_id,
        venue=venue,
        venue_mode=venue_mode,
        reason=reason,
    )
    inserted = store.append(decision)
    if not inserted and getattr(store, "last_error", None):
        raise RuntimeError("STRUCTURAL_STOP_COMPARISON_DECISION_PERSIST_FAILED")
    if inserted:
        _legacy.logger.info(
            "[PAPER-STRUCTURAL-STOP-COMPARISON] DECISION %s",
            json.dumps(decision, ensure_ascii=False, separators=(",", ":")),
        )


def _record_structural_stop_comparison_start(position: Any) -> None:
    store = _paper_structural_stop_comparison_store
    if store is None:
        return
    position_id = str(getattr(position, "position_id", "") or "").strip()
    if not position_id:
        return
    with _paper_structural_stop_comparison_lock:
        if position_id in _paper_structural_stop_comparison_active:
            return

    metadata = getattr(position, "entry_metadata", None)
    metadata = metadata if isinstance(metadata, dict) else {}
    capture_id = str(metadata.get("entry_v2_shadow_capture_id") or "").strip()
    venue, _stream, report_mode = _structural_stop_comparison_stream()
    if not capture_id:
        _record_structural_stop_comparison_decision(
            position,
            source_capture_id="",
            venue=venue,
            venue_mode=report_mode,
            reason="ENTRY_V2_CAPTURE_ID_UNAVAILABLE",
        )
        return

    capture_store = getattr(_entry_v2_runtime_capture, "capture_store", None)
    lookup = getattr(capture_store, "get_by_identity", None)
    if not callable(lookup):
        _record_structural_stop_comparison_decision(
            position,
            source_capture_id=capture_id,
            venue=venue,
            venue_mode=report_mode,
            reason="ENTRY_V2_CAPTURE_LOOKUP_UNAVAILABLE",
        )
        return
    try:
        capture = lookup(capture_id)
    except Exception as exc:
        _legacy.logger.exception(
            "[PAPER-STRUCTURAL-STOP-COMPARISON] capture lookup failed position_id=%s",
            position_id,
        )
        _record_structural_stop_comparison_decision(
            position,
            source_capture_id=capture_id,
            venue=venue,
            venue_mode=report_mode,
            reason=f"ENTRY_V2_CAPTURE_LOOKUP_{type(exc).__name__}",
        )
        return
    if not isinstance(capture, dict) or str(capture.get("capture_id") or "") != capture_id:
        _record_structural_stop_comparison_decision(
            position,
            source_capture_id=capture_id,
            venue=venue,
            venue_mode=report_mode,
            reason="EXACT_ENTRY_V2_CAPTURE_NOT_FOUND",
        )
        return

    fee_rate = float(
        getattr(getattr(runtime, "execution_adapter", None), "fee_rate", 0.001) or 0.001
    )
    try:
        watch = build_structural_stop_comparison_watch(
            capture,
            position,
            fee_rate=fee_rate,
            venue=venue,
            venue_mode=report_mode,
        )
    except (TypeError, ValueError) as exc:
        _record_structural_stop_comparison_decision(
            position,
            source_capture_id=capture_id,
            venue=venue,
            venue_mode=report_mode,
            reason=str(exc) or type(exc).__name__,
        )
        return

    inserted = store.append(watch)
    if not inserted and getattr(store, "last_error", None):
        raise RuntimeError("STRUCTURAL_STOP_COMPARISON_START_PERSIST_FAILED")
    if str(watch.get("status") or "").upper() == "OBSERVING":
        with _paper_structural_stop_comparison_lock:
            _paper_structural_stop_comparison_active[position_id] = dict(watch)
    if inserted:
        _legacy.logger.info(
            "[PAPER-STRUCTURAL-STOP-COMPARISON] START %s",
            json.dumps(watch, ensure_ascii=False, separators=(",", ":")),
        )


# This wrapper is installed after EntryV2RuntimeCapture's repository wrapper.
# Consequently it sees the exact capture identity copied onto the new Paper
# position. It only observes successful repository inserts.
_paper_structural_original_repository_add = runtime.repository.add


def _paper_repository_add_with_structural_stop_watch(position: Any):
    result = _paper_structural_original_repository_add(position)
    try:
        _record_structural_stop_comparison_start(position)
    except Exception:
        _legacy.logger.exception(
            "[PAPER-STRUCTURAL-STOP-COMPARISON] START observer failed position_id=%s",
            getattr(position, "position_id", "UNKNOWN"),
        )
    return result


runtime.repository.add = _paper_repository_add_with_structural_stop_watch


def _structural_stop_actual_paper_outcome(position_id: str) -> dict[str, Any] | None:
    getter = getattr(runtime.repository, "get", None)
    if not callable(getter):
        return None
    try:
        position = getter(position_id)
    except Exception:
        return None
    if position is None:
        return None
    status = str(getattr(getattr(position, "status", ""), "name", getattr(position, "status", ""))).upper()
    if status != "CLOSED":
        return {"status": status or "UNKNOWN"}
    exit_metadata = getattr(position, "exit_metadata", None)
    exit_metadata = exit_metadata if isinstance(exit_metadata, dict) else {}
    return {
        "status": status,
        "realized_pnl": float(getattr(position, "realized_pnl", 0.0) or 0.0),
        "total_fees": float(getattr(position, "total_fees", 0.0) or 0.0),
        "exit_price": exit_metadata.get("exit_price", getattr(position, "current_price", None)),
        "exit_reason": exit_metadata.get("exit_reason") or exit_metadata.get("reason") or "",
    }


def _advance_structural_stop_comparison_watches() -> None:
    store = _paper_structural_stop_comparison_store
    if store is None:
        return
    with _paper_structural_stop_comparison_lock:
        watches = list(_paper_structural_stop_comparison_active.items())

    for position_id, previous in watches:
        updated = dict(previous)
        state_changed = False
        if str(updated.get("status") or "").upper() == "OBSERVING":
            venue_mode = str(updated.get("venue_mode") or PAPER_VENUE_MODE)
            venue, stream, _report_mode = _structural_stop_comparison_stream(venue_mode)
            get_history = getattr(stream, "get_kline_history", None)
            if not callable(get_history):
                if venue_mode not in _paper_structural_stop_comparison_missing_stream_warned:
                    _paper_structural_stop_comparison_missing_stream_warned.add(venue_mode)
                    _legacy.logger.warning(
                        "[PAPER-STRUCTURAL-STOP-COMPARISON] selected venue stream unavailable venue_mode=%s venue=%s",
                        venue_mode,
                        venue,
                    )
                continue
            try:
                candles = get_history(str(updated.get("symbol") or ""), "5m", 60) or []
                updated, state_changed = advance_structural_stop_comparison(previous, candles)
            except Exception:
                _legacy.logger.exception(
                    "[PAPER-STRUCTURAL-STOP-COMPARISON] path update failed position_id=%s",
                    position_id,
                )
                continue

        actual_outcome = _structural_stop_actual_paper_outcome(position_id)
        if actual_outcome is not None and updated.get("actual_paper_outcome") != actual_outcome:
            updated["actual_paper_outcome"] = actual_outcome
            state_changed = True

        # A path pair may finish before the real Paper position closes. Keep
        # its completed counterfactual snapshot checkpointed until the actual
        # position outcome is available, then include both in one FINAL event.
        actual_status = (
            str(actual_outcome.get("status") or "").upper()
            if isinstance(actual_outcome, dict) else "NOT_FOUND"
        )
        actual_still_open = actual_status in {
            "OPEN", "HOLD", "REVIEW_REQUIRED", "PARTIALLY_CLOSED"
        }
        if str(updated.get("status") or "").upper() == "OBSERVING" or actual_still_open:
            # Checkpoint only when a new closed candle (or a real Paper state
            # transition) changes the comparison. START is upserted in-place.
            if state_changed:
                try:
                    persisted = store.upsert(updated)
                    if not persisted and getattr(store, "last_error", None):
                        raise RuntimeError("STRUCTURAL_STOP_COMPARISON_CHECKPOINT_FAILED")
                except Exception:
                    _legacy.logger.exception(
                        "[PAPER-STRUCTURAL-STOP-COMPARISON] checkpoint failed position_id=%s",
                        position_id,
                    )
            with _paper_structural_stop_comparison_lock:
                current = _paper_structural_stop_comparison_active.get(position_id)
                if current is not None:
                    _paper_structural_stop_comparison_active[position_id] = updated
            continue

        final_event = dict(updated)
        final_event["record_type"] = "FINAL"
        final_event["record_id"] = f"{position_id}:FINAL"
        final_event["capture_id"] = f"{position_id}:FINAL"
        try:
            inserted = store.append(final_event)
            if not inserted and getattr(store, "last_error", None):
                raise RuntimeError("STRUCTURAL_STOP_COMPARISON_FINAL_PERSIST_FAILED")
            with _paper_structural_stop_comparison_lock:
                _paper_structural_stop_comparison_active.pop(position_id, None)
            if inserted:
                _legacy.logger.info(
                    "[PAPER-STRUCTURAL-STOP-COMPARISON] FINAL %s",
                    json.dumps(final_event, ensure_ascii=False, separators=(",", ":")),
                )
        except Exception:
            # Keep completed in-memory evidence and retry the idempotent FINAL
            # insert on a later market cycle; the Paper position is untouched.
            with _paper_structural_stop_comparison_lock:
                _paper_structural_stop_comparison_active[position_id] = final_event
            _legacy.logger.exception(
                "[PAPER-STRUCTURAL-STOP-COMPARISON] final persistence failed position_id=%s",
                position_id,
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




@app.get("/paper/market-data-comparison")
def paper_market_data_comparison():
    """Optional historical report; disabled while isolated venue labs are validated."""
    if not PAPER_CROSS_VENUE_DIAGNOSTICS_ENABLED:
        return jsonify({
            "enabled": False,
            "reason": "DISABLED_BY_CONFIGURATION",
            "message": "Cross-venue comparison is paused; market alignment safety checks remain active.",
        }), 200
    records = []
    if _paper_outcome_store is not None:
        try:
            records = _paper_outcome_store.read_all()
        except Exception:
            _legacy.logger.exception("Market-data source comparison read failed")
    return jsonify(
        compare_paper_outcomes_by_market_data_source(records)
    ), 200


@app.get("/paper/entry-funnel-report")
def _paper_entry_funnel_report():
    """Read-only daily attribution of captured candidates through final Paper disposition."""
    try:
        brain_records = _brain_authority_store.read_all()
        if getattr(_brain_authority_store, "last_error", None):
            raise RuntimeError("BRAIN_AUTHORITY_EVIDENCE_READ_FAILED")
        final_records = (
            _paper_entry_funnel_store.read_all()
            if _paper_entry_funnel_store is not None
            else []
        )
        if _paper_entry_funnel_store is not None and getattr(_paper_entry_funnel_store, "last_error", None):
            raise RuntimeError("PAPER_ENTRY_FUNNEL_EVIDENCE_READ_FAILED")
        payload = build_entry_funnel_report(brain_records + final_records)
        payload["generated_at_utc"] = datetime.now(timezone.utc).isoformat()
        payload["persistent_store"] = {
            "brain_authority": _brain_authority_store.summary(),
            "final_dispositions": (
                _paper_entry_funnel_store.summary()
                if _paper_entry_funnel_store is not None
                else {"backend": "DISABLED"}
            ),
        }
        return jsonify(payload), 200
    except Exception as exc:
        _legacy.logger.exception("Paper entry funnel report failed")
        return jsonify({"available": False, "mode": "PAPER_ONLY", "error": type(exc).__name__}), 503


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
        if record_profit_protection_net_floor_shadow(
            position, runtime.facade.calculator
        ):
            runtime.repository.update(position)
            shadow_trial = position.metadata.get("paper_profit_protection_shadow", {})
            _legacy.logger.info(
                "[PAPER-PROFIT-PROTECTION-SHADOW] %s",
                json.dumps(
                    {
                        "venue": "MAIN",
                        "position_id": str(position.position_id),
                        "symbol": str(position.symbol).upper(),
                        "trade_mode": str(position.entry_metadata.get("trade_mode", "UNKNOWN")).upper(),
                        "status": shadow_trial.get("status"),
                        "triggered": shadow_trial.get("triggered"),
                        "current_gain_percent": shadow_trial.get("current_gain_percent"),
                        "peak_gain_percent": shadow_trial.get("peak_gain_percent"),
                        "retrace_percent": shadow_trial.get("retrace_percent"),
                        "net_pnl_estimate_after_fees": shadow_trial.get("net_pnl_estimate_after_fees"),
                        "exit_price": shadow_trial.get("exit_price"),
                        "reason": shadow_trial.get("reason"),
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            )
        protection_snapshot = profit_protection_snapshot(
            entry_price=position.entry_price,
            current_price=current,
            highest_price=position.highest_price,
            max_profit_percent=position.max_profit_percent,
        )
        if protection_snapshot["triggered"]:
            protection_detail = {
                "position_id": str(position.position_id),
                "symbol": str(position.symbol).upper(),
                "trade_mode": str(position.entry_metadata.get("trade_mode", "UNKNOWN")).upper(),
                **protection_snapshot,
            }
            position.metadata["paper_profit_protection_detail"] = protection_detail
            _legacy.logger.info(
                "PAPER PROFIT PROTECTION TRIGGER %s",
                json.dumps(protection_detail, ensure_ascii=False, separators=(",", ":")),
            )
            decision = PositionExitDecision(True, PositionExitReason.TRAILING_STOP, current, "Paper Protection: calibrated profitable retracement before TP")
            result = runtime.facade.execute_decision(position.position_id, decision)
            if result is not None and result.status is PositionStatus.CLOSED:
                result.exit_metadata["paper_profit_protection"] = True
                result.exit_metadata["paper_profit_protection_detail"] = protection_detail
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


def _log_paper_signal_cycle_summary() -> None:
    """Emit compact per-cycle score/signal/gate counts; diagnostics only."""
    try:
        summary = build_paper_signal_cycle_summary(
            _legacy.latest_scores,
            scalp_threshold=SCALP_SCORE_THRESHOLD,
            swing_threshold=SWING_SCORE_THRESHOLD,
            venue_mode=PAPER_VENUE_MODE,
        )
        summary["generated_at_epoch_ms"] = int(time.time() * 1000)
        _legacy.logger.info(
            "[PAPER-SIGNAL-FUNNEL] %s",
            json.dumps(summary, ensure_ascii=False, separators=(",", ":")),
        )
    except Exception:
        _legacy.logger.exception("Paper signal funnel cycle summary failed")


def _process_market_cycle_with_overlays():
    _reset_entry_diagnostics_for_cycle()
    original_has_position = runtime.controller.has_position
    runtime.controller.has_position = _lane_aware_existing_position_gate
    try:
        result = _paper_original_process_market_cycle()
    finally:
        runtime.controller.has_position = original_has_position
    _log_paper_signal_cycle_summary()
    try:
        shadow_summary = _entry_v2_runtime_capture.capture_cycle()
        runtime.last_entry_diagnostics.setdefault("__entry_v2_shadow__", {})["summary"] = shadow_summary
    except Exception:
        _legacy.logger.exception("Entry v2 shadow capture failed")
    try:
        _record_precalibration_shadow_candidates()
    except Exception:
        _legacy.logger.exception("Pre-calibration Paper shadow candidate evaluation failed")
    try:
        _advance_precalibration_shadow_watches()
    except Exception:
        _legacy.logger.exception("Pre-calibration Paper shadow path advancement failed")
    try:
        _advance_blocked_entry_shadow_watches()
    except Exception:
        _legacy.logger.exception("Blocked-entry Paper shadow tracker failed")
    try:
        _advance_structural_stop_comparison_watches()
    except Exception:
        _legacy.logger.exception("Structural-stop Paper comparison tracker failed")
    try:
        _seed_existing_hosted_paper_structural_stop_positions()
    except Exception:
        _legacy.logger.exception("Hosted venue structural-stop existing-position seed failed")
    try:
        _hosted_paper_structural_stop_coordinator.advance()
    except Exception:
        _legacy.logger.exception("Hosted venue structural-stop comparison tracker failed")
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


# Optional staged Paper comparison labs in the MAIN process.
# Disabled by default. Monitor-only is the safe first activation stage:
# public market data and scoring run, while entries and DB writes remain off.
_hosted_paper_lab_runner = None
_hosted_labs_enabled = os.getenv("PAPER_HOSTED_VENUE_LABS", "0").strip().lower() in {"1", "true", "yes", "on"}
_hosted_requested_venues_raw = os.getenv("PAPER_HOSTED_LAB_VENUES", "BINANCE,BYBIT,OKX")
_hosted_requested_venues = tuple(dict.fromkeys(
    part.strip().upper()
    for part in _hosted_requested_venues_raw.split(",")
    if part.strip()
))
_hosted_invalid_venues = sorted(set(_hosted_requested_venues) - {"BINANCE", "BYBIT", "OKX"})
_hosted_monitor_only = os.getenv("PAPER_HOSTED_LAB_ALLOW_ENTRIES", "0").strip().lower() not in {"1", "true", "yes", "on"}
if _hosted_labs_enabled:
    if _hosted_invalid_venues or not _hosted_requested_venues:
        _legacy.logger.error(
            "[HOSTED-PAPER-LABS] disabled: invalid venue selection=%s",
            _hosted_invalid_venues or "EMPTY",
        )
    elif PAPER_VENUE_MODE != "MIXED":
        _legacy.logger.error(
            "[HOSTED-PAPER-LABS] disabled: MAIN must remain in MIXED mode"
        )
    elif "BINANCE" in _hosted_requested_venues and not _PAPER_MAIN_BINANCE_ONLY:
        _legacy.logger.error(
            "[HOSTED-PAPER-LABS] disabled: Binance lab requires MAIN's complete Binance Relay universe"
        )
    elif "BYBIT" in _hosted_requested_venues and not _BYBIT_MARKET_DATA_ENABLED:
        _legacy.logger.error(
            "[HOSTED-PAPER-LABS] disabled: Bybit public Spot cold-start data is not enabled"
        )
    elif "OKX" in _hosted_requested_venues and not _OKX_MARKET_DATA_ENABLED:
        _legacy.logger.error(
            "[HOSTED-PAPER-LABS] disabled: OKX public Spot cold-start data is not enabled"
        )
    else:
        try:
            _hosted_bybit_stream = None
            _hosted_okx_stream = None
            if "BYBIT" in _hosted_requested_venues:
                _hosted_bybit_stream = BybitMarketStream(
                    TRADING_SYMBOLS,
                    intervals=("5m", "15m", "1h", "4h"),
                )
            if "OKX" in _hosted_requested_venues:
                _hosted_okx_stream = OKXMarketStream(
                    TRADING_SYMBOLS,
                    intervals=("5m", "15m", "1h", "4h"),
                    base_url=os.getenv(
                        "OKX_MARKET_DATA_WS_PUBLIC_URL",
                        "wss://ws.okx.com/ws/v5/public",
                    ).strip(),
                    business_base_url=os.getenv(
                        "OKX_MARKET_DATA_WS_BUSINESS_URL",
                        "wss://ws.okx.com/ws/v5/business",
                    ).strip(),
                )
            try:
                _hosted_scan_batch_size = max(
                    1, min(8, int(os.getenv("PAPER_HOSTED_LAB_SCAN_BATCH", "4")))
                )
            except (TypeError, ValueError):
                _hosted_scan_batch_size = 4

            _hosted_paper_lab_runner = create_hosted_paper_lab_runner(
                symbols=list(TRADING_SYMBOLS),
                binance_stream=_binance_market_stream,
                bybit_stream=_hosted_bybit_stream,
                okx_stream=_hosted_okx_stream,
                database_url=database_url_from_env() if not _hosted_monitor_only else None,
                bybit_client=_bybit_client if "BYBIT" in _hosted_requested_venues else None,
                okx_client=_okx_client if "OKX" in _hosted_requested_venues else None,
                initial_cash=INITIAL_CASH,
                fee_rate=FEE_RATE,
                scan_batch_size=_hosted_scan_batch_size,
                enabled_venues=_hosted_requested_venues,
                monitor_only=_hosted_monitor_only,
                telegram_notifier=_legacy.send_telegram_message,
            )
            if _hosted_paper_lab_runner is not None and _hosted_paper_lab_runner.enabled:
                _attach_hosted_paper_structural_stop_comparison(_hosted_paper_lab_runner)
                _hosted_paper_lab_runner.start()
        except Exception:
            _legacy.logger.exception(
                "[HOSTED-PAPER-LABS] startup failed; MAIN remains unaffected"
            )
            try:
                if _hosted_paper_lab_runner is not None:
                    _hosted_paper_lab_runner.close()
            except Exception:
                pass
            _hosted_paper_lab_runner = None


@app.get("/paper/hosted-labs")
def _hosted_paper_labs_health():
    runner = globals().get("_hosted_paper_lab_runner")
    if runner is None:
        return jsonify({
            "enabled": False,
            "mode": "PAPER_ONLY",
            "reason": "HOSTED_PAPER_LABS_DISABLED_OR_NOT_READY",
        }), 200
    payload = runner.snapshot()
    payload["mode"] = "MONITOR_ONLY" if runner.monitor_only else "PAPER_ONLY"
    payload["entries_enabled"] = not runner.monitor_only
    payload["structural_stop_comparison"] = _hosted_paper_structural_stop_coordinator.snapshot()
    return jsonify(payload), 200



def _hosted_lab_daily_report_for_venue(venue: str, date_key: str) -> str:
    """Build one lab's local-day report from its own durable outcome store."""
    venue_name = str(venue or "").strip().upper()
    runner = globals().get("_hosted_paper_lab_runner")
    if venue_name not in {"BYBIT", "OKX"} or runner is None:
        raise ValueError("HOSTED_PAPER_LAB_UNAVAILABLE")
    lab = runner.labs.get(venue_name)
    store = getattr(lab, "outcomes", None)
    if store is None or not callable(getattr(store, "read_time_range", None)):
        raise RuntimeError("HOSTED_PAPER_LAB_OUTCOME_STORE_UNAVAILABLE")

    local_start = _legacy.datetime.strptime(date_key, "%Y-%m-%d").replace(
        tzinfo=_legacy.REPORT_TIMEZONE
    )
    local_end = local_start + _legacy.timedelta(days=1)
    start_utc = local_start.astimezone(_legacy.timezone.utc).isoformat()
    end_utc = local_end.astimezone(_legacy.timezone.utc).isoformat()
    outcomes = store.read_time_range("closed_at_utc", start_utc, end_utc)
    if getattr(store, "last_error", None):
        raise RuntimeError("HOSTED_PAPER_LAB_OUTCOME_READ_FAILED")
    return format_hosted_lab_daily_report(
        venue_name,
        date_key,
        outcomes,
        paper_cash=lab.adapter.balance.cash,
        open_positions=len(lab.repository.get_open_positions()),
    )


@app.get("/paper/hosted-labs/daily-reports/<date_key>")
def _hosted_paper_lab_daily_reports(date_key: str):
    """Read-only daily reports for the isolated Bybit and OKX Paper portfolios."""
    try:
        _legacy.datetime.strptime(date_key, "%Y-%m-%d")
    except (TypeError, ValueError):
        return jsonify({"available": False, "reason": "INVALID_DATE"}), 400
    runner = globals().get("_hosted_paper_lab_runner")
    if runner is None:
        return jsonify({"available": False, "reason": "HOSTED_PAPER_LABS_UNAVAILABLE"}), 503
    reports = {}
    for venue in ("BYBIT", "OKX"):
        if venue not in runner.labs:
            continue
        try:
            reports[venue] = _hosted_lab_daily_report_for_venue(venue, date_key)
        except Exception:
            _legacy.logger.exception(
                "Hosted Paper daily report build failed venue=%s date=%s",
                venue,
                date_key,
            )
            reports[venue] = None
    return jsonify({
        "available": bool(reports) and all(report is not None for report in reports.values()),
        "mode": "PAPER_ONLY",
        "date": date_key,
        "reports": reports,
    }), 200


def _hosted_lab_daily_report_loop() -> None:
    """Send one separate Telegram daily close report for each hosted lab."""
    report_date = _legacy.datetime.now(_legacy.REPORT_TIMEZONE).strftime("%Y-%m-%d")
    sent_dates: dict[str, str] = {}
    last_attempt_at: dict[str, float] = {}
    while True:
        try:
            today = _legacy.datetime.now(_legacy.REPORT_TIMEZONE).strftime("%Y-%m-%d")
            if today != report_date:
                runner = globals().get("_hosted_paper_lab_runner")
                venues = [
                    venue for venue in ("BYBIT", "OKX")
                    if runner is not None and venue in runner.labs
                ]
                if not venues:
                    report_date = today
                    sent_dates.clear()
                    last_attempt_at.clear()
                else:
                    for venue in venues:
                        if sent_dates.get(venue) == report_date:
                            continue
                        now = time.monotonic()
                        attempt_key = f"{report_date}:{venue}"
                        if now - last_attempt_at.get(attempt_key, 0.0) < 300.0:
                            continue
                        last_attempt_at[attempt_key] = now
                        try:
                            report = _hosted_lab_daily_report_for_venue(venue, report_date)
                            if _legacy.send_telegram_message(report):
                                sent_dates[venue] = report_date
                                _legacy.logger.info(
                                    "[HOSTED-PAPER-LAB-DAILY-REPORT] sent venue=%s date=%s",
                                    venue,
                                    report_date,
                                )
                            else:
                                _legacy.logger.warning(
                                    "[HOSTED-PAPER-LAB-DAILY-REPORT] Telegram send failed venue=%s date=%s",
                                    venue,
                                    report_date,
                                )
                        except Exception:
                            _legacy.logger.exception(
                                "[HOSTED-PAPER-LAB-DAILY-REPORT] failed venue=%s date=%s",
                                venue,
                                report_date,
                            )
                    if all(sent_dates.get(venue) == report_date for venue in venues):
                        report_date = today
                        sent_dates.clear()
                        last_attempt_at.clear()
        except Exception:
            _legacy.logger.exception("Hosted Paper lab daily report loop failed")
        time.sleep(30.0)


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
        if not _should_notify_market_health(
            venue_mode=PAPER_VENUE_MODE,
            changed=changed,
            heartbeat_due=heartbeat_due,
            force=force,
        ):
            return
        _MARKET_HEALTH_STATE = state
        _MARKET_HEALTH_LAST_ALERT_AT = now
    message = f"📡 PAPER MARKET HEALTH\nState: {state}\n{detail}\nPAPER ONLY"
    try:
        _legacy.send_telegram_message(message)
    except Exception:
        _legacy.logger.exception("Market health Telegram notification failed")


def _observe_market_health() -> None:
    guard_snapshot = _market_data_guard_snapshot()
    data_count = len(_legacy.latest_scores or {})
    symbol_count = len(TRADING_SYMBOLS)
    status_code = guard_snapshot.get("status_code")
    blocked = bool(guard_snapshot.get("blocked"))
    last_path = guard_snapshot.get("last_path") or ""
    retry_in = float(guard_snapshot.get("blocked_for_seconds", 0.0) or 0.0)

    try:
        active_venue, websocket_snapshot = _selected_venue_websocket_snapshot()
    except Exception as exc:  # pragma: no cover - health reporting must remain isolated
        active_venue = str(PAPER_VENUE_MODE or "UNKNOWN")
        websocket_snapshot = {
            "available": False,
            "connected": False,
            "event_stream_healthy": False,
            "reason": f"{type(exc).__name__}: {exc}",
        }
    summary = build_paper_market_health_summary(
        scored_symbol_count=data_count,
        symbol_count=symbol_count,
        local_kline_cache_entries=guard_snapshot.get("kline_cache_entries", 0),
        venue=active_venue,
        websocket_snapshot=websocket_snapshot,
    )

    # A previous rate-limit response remains diagnostic history after the
    # circuit reopens. Only report it as active while that provider's guard
    # is blocked; the label must match the active venue's actual guard.
    guard_alert_label = market_data_guard_alert_label(
        venue_mode=PAPER_VENUE_MODE,
        status_code=status_code,
        blocked=blocked,
    )
    if guard_alert_label and "RATE LIMIT" in guard_alert_label:
        _market_health_notify(
            guard_alert_label,
            f"Path: {last_path}\nRetry in: {retry_in:.0f}s\n{summary['detail']}",
        )
        return
    if blocked:
        _market_health_notify(
            guard_alert_label or "MARKET DATA CIRCUIT OPEN",
            f"Local protection is waiting; retry window: {retry_in:.0f}s\n{summary['detail']}",
        )
        return
    if data_count <= 0:
        _market_health_notify(
            "MARKET DATA DOWN",
            f"{summary['detail']}\nLast guard status: {status_code or 'none'}",
        )
        return
    _market_health_notify(summary["state"], summary["detail"])


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


@app.get("/paper/runtime-memory")
def _paper_runtime_memory():
    """Read-only bounded-size runtime counters for diagnosing process memory growth."""
    try:
        payload = build_paper_runtime_memory_snapshot(runtime)
        payload["evidence"] = {
            "paper_outcome_logged_position_ids": len(_paper_outcome_evidence_logged_ids),
        }
        return jsonify(payload), 200
    except Exception as exc:  # diagnostics must never affect Paper execution
        _legacy.logger.exception("Paper runtime memory snapshot failed")
        return jsonify({
            "available": False,
            "mode": "PAPER_ONLY",
            "error": type(exc).__name__,
        }), 503


@app.get("/paper/entry-gate-summary")
def _paper_entry_gate_summary():
    """Small, read-only entry diagnostic; avoid the full evidence report/trace payload."""
    payload = build_paper_entry_gate_summary(
        _legacy.latest_scores,
        scalp_threshold=SCALP_SCORE_THRESHOLD,
        swing_threshold=SWING_SCORE_THRESHOLD,
        venue_mode=PAPER_VENUE_MODE,
        entry_diagnostics=runtime.last_entry_diagnostics,
    )
    payload["generated_at_utc"] = datetime.now(timezone.utc).isoformat()
    return jsonify(payload), 200


@app.get("/paper/structural-stop-comparison")
def _paper_structural_stop_comparison_report():
    """Read-only paired ATR/structural stop evidence for Paper positions."""
    store = _paper_structural_stop_comparison_store
    venue_mode = str(PAPER_VENUE_MODE or "UNKNOWN").upper()
    if store is None:
        return jsonify({
            "available": False,
            "mode": "PAPER_ONLY",
            "venue_mode": venue_mode,
            "reason": "STRUCTURAL_STOP_COMPARISON_STORE_UNAVAILABLE",
        }), 503
    try:
        records = store.read_all()
        if getattr(store, "last_error", None):
            return jsonify({
                "available": False,
                "mode": "PAPER_ONLY",
                "venue_mode": venue_mode,
                "reason": "STRUCTURAL_STOP_COMPARISON_READ_FAILED",
            }), 503
        records.extend(_hosted_paper_structural_stop_coordinator.read_all_records())
        payload = build_structural_stop_comparison_report(records)
        payload["current_service_venue_mode"] = venue_mode
        payload["current_service_venue"] = _structural_stop_comparison_stream()[0]
        payload["hosted_lab_monitor"] = _hosted_paper_structural_stop_coordinator.snapshot()
        _legacy.logger.warning(
            "[PAPER-STRUCTURAL-STOP-SAMPLE-PROGRESS] %s",
            json.dumps(
                {
                    "sample_progress_by_venue_and_trade_mode": {
                        key: {
                            field: value for field, value in cohort.items()
                            if field != "samples"
                        }
                        for key, cohort in (
                            payload.get("sample_progress_by_venue_and_trade_mode") or {}
                        ).items()
                    },
                    "coverage": payload.get("coverage"),
                    "comparison": payload.get("comparison"),
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        )
        return jsonify(payload), 200
    except Exception as exc:
        _legacy.logger.exception("Structural-stop comparison report failed")
        return jsonify({
            "available": False,
            "mode": "PAPER_ONLY",
            "venue_mode": venue_mode,
            "reason": type(exc).__name__,
        }), 503


@app.get("/paper/shadow-evidence-report")
def _paper_shadow_evidence_report():
    """On-demand aggregate report for stop/recovery experiments; never an execution gate."""
    payload = _safe_paper_shadow_evidence_report_payload()
    return jsonify(payload), 200 if payload.get("available") else 503


@app.get("/paper/outcome-analysis")
def _paper_outcome_analysis():
    """Read-only aggregate analysis of closed Paper outcomes for this venue."""
    store = globals().get("_paper_outcome_store")
    venue_mode = str(globals().get("PAPER_VENUE_MODE", "UNKNOWN") or "UNKNOWN")
    if store is None or not callable(getattr(store, "read_all", None)):
        return jsonify({
            "available": False,
            "mode": "PAPER",
            "venue_mode": venue_mode,
            "reason": "PAPER_OUTCOME_STORE_UNAVAILABLE",
        }), 503
    try:
        records = store.read_all()
        if getattr(store, "last_error", None):
            _legacy.logger.error(
                "Paper outcome analysis read failed: %s",
                str(getattr(store, "last_error", "")).split(":", 1)[0],
            )
            return jsonify({
                "available": False,
                "mode": "PAPER",
                "venue_mode": venue_mode,
                "reason": "PAPER_OUTCOME_READ_FAILED",
            }), 503
        payload = build_paper_outcome_analysis(records)
        payload.update({
            "available": True,
            "mode": "PAPER",
            "venue_mode": venue_mode,
            "source": "Postgres PAPER_OUTCOME",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        })
        return jsonify(payload), 200
    except Exception as exc:  # keep a diagnostics endpoint from affecting Paper execution
        _legacy.logger.exception("Paper outcome aggregate analysis failed")
        return jsonify({
            "available": False,
            "mode": "PAPER",
            "venue_mode": venue_mode,
            "reason": "PAPER_OUTCOME_ANALYSIS_FAILED",
            "error": type(exc).__name__,
        }), 503




_PAPER_FORENSICS_WINDOW_DAYS = 90
_PAPER_FORENSICS_START_LOCK = threading.Lock()
_PAPER_FORENSICS_STARTED = False


def _paper_forensics_time_range() -> tuple[str, str]:
    end = datetime.now(timezone.utc)
    start = datetime.fromtimestamp(
        end.timestamp() - _PAPER_FORENSICS_WINDOW_DAYS * 24.0 * 60.0 * 60.0,
        tz=timezone.utc,
    )
    return start.isoformat(), end.isoformat()


def _read_forensic_evidence(store: Any, timestamp_field: str, start: str, end: str):
    if store is None or not callable(getattr(store, "read_time_range", None)):
        raise RuntimeError("EVIDENCE_STORE_UNAVAILABLE")
    rows = store.read_time_range(timestamp_field, start, end)
    if getattr(store, "last_error", None):
        raise RuntimeError("EVIDENCE_STORE_READ_FAILED")
    return rows


def _forensic_capture_id(outcome: Mapping[str, Any]) -> str:
    entry_v2 = outcome.get("entry_v2", {})
    entry_v2 = entry_v2 if isinstance(entry_v2, dict) else {}
    chain = outcome.get("entry_decision_chain", {})
    chain = chain if isinstance(chain, dict) else {}
    chain_v2 = chain.get("entry_v2", {})
    chain_v2 = chain_v2 if isinstance(chain_v2, dict) else {}
    brain = outcome.get("brain", {})
    brain = brain if isinstance(brain, dict) else {}
    return str(
        entry_v2.get("capture_id")
        or chain_v2.get("capture_id")
        or brain.get("capture_id")
        or ""
    ).strip()


def _build_linked_entry_outcome_forensics() -> dict[str, Any]:
    """Read closed outcomes first, then retrieve only their matching entry captures."""
    start, end = _paper_forensics_time_range()
    venues: dict[str, Any] = {}

    # MAIN's capture store can contain many candle windows. Do not use
    # read_all()/read_time_range() on that store: fetch only capture IDs
    # referenced by closed outcomes through its indexed identity key.
    main_capture_store = getattr(
        globals().get("_entry_v2_runtime_capture"),
        "capture_store",
        None,
    )
    try:
        main_outcomes = _read_forensic_evidence(
            globals().get("_paper_outcome_store"),
            "closed_at_utc",
            start,
            end,
        )
        main_capture_ids = {
            capture_id
            for outcome in main_outcomes
            if isinstance(outcome, dict)
            for capture_id in (_forensic_capture_id(outcome),)
            if capture_id
        }
        if main_capture_store is None or not callable(
            getattr(main_capture_store, "read_by_identity_keys", None)
        ):
            raise RuntimeError("MAIN_CAPTURE_SELECTIVE_READ_UNAVAILABLE")
        main_captures = main_capture_store.read_by_identity_keys(main_capture_ids)
        if getattr(main_capture_store, "last_error", None):
            raise RuntimeError("MAIN_CAPTURE_SELECTIVE_READ_FAILED")
        _legacy.logger.info(
            "[PAPER-FORENSICS] MAIN outcomes=%d referenced_capture_ids=%d matched_captures=%d",
            len(main_outcomes),
            len(main_capture_ids),
            len(main_captures),
        )
        venues["MAIN"] = build_linked_entry_outcome_analysis(
            "MAIN",
            main_outcomes,
            main_captures,
        )
        del main_outcomes
        del main_captures
    except Exception as exc:
        _legacy.logger.exception("MAIN linked entry/outcome forensics failed")
        venues["MAIN"] = {
            "available": False,
            "reason": str(exc).split(":", 1)[0],
        }

    runner = globals().get("_hosted_paper_lab_runner")
    for venue in ("BYBIT", "OKX"):
        lab = runner.labs.get(venue) if runner is not None else None
        if lab is None:
            venues[venue] = {"available": False, "reason": "HOSTED_LAB_UNAVAILABLE"}
            continue
        try:
            outcomes = _read_forensic_evidence(
                getattr(lab, "outcomes", None),
                "closed_at_utc",
                start,
                end,
            )
            position_ids = {
                str(outcome.get("position_id") or "").strip()
                for outcome in outcomes
                if isinstance(outcome, dict)
                and str(outcome.get("position_id") or "").strip()
            }
            capture_store = getattr(lab, "entry_captures", None)
            if capture_store is None or not callable(
                getattr(capture_store, "read_by_payload_values", None)
            ):
                raise RuntimeError(f"{venue}_CAPTURE_SELECTIVE_READ_UNAVAILABLE")
            captures = capture_store.read_by_payload_values("position_id", position_ids)
            if getattr(capture_store, "last_error", None):
                raise RuntimeError(f"{venue}_CAPTURE_SELECTIVE_READ_FAILED")
            _legacy.logger.info(
                "[PAPER-FORENSICS] %s outcomes=%d referenced_position_ids=%d matched_captures=%d",
                venue,
                len(outcomes),
                len(position_ids),
                len(captures),
            )
            venues[venue] = build_linked_entry_outcome_analysis(
                venue,
                outcomes,
                captures,
            )
            del outcomes
            del captures
        except Exception as exc:
            _legacy.logger.exception("%s linked entry/outcome forensics failed", venue)
            venues[venue] = {
                "available": False,
                "reason": str(exc).split(":", 1)[0],
            }

    return {
        "available": all(
            isinstance(venues.get(venue), dict)
            and venues[venue].get("coverage") is not None
            for venue in ("MAIN", "BYBIT", "OKX")
        ),
        "mode": "PAPER_ONLY",
        "window_days": _PAPER_FORENSICS_WINDOW_DAYS,
        "window_start_utc": start,
        "window_end_utc": end,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "join_keys": {
            "MAIN": "entry_v2.capture_id -> ENTRY_V2_CAPTURE.capture_id (selective identity lookup)",
            "BYBIT": "PAPER_OUTCOME.position_id -> ENTRY_V2_CAPTURE.position_id (selective JSON payload lookup)",
            "OKX": "PAPER_OUTCOME.position_id -> ENTRY_V2_CAPTURE.position_id (selective JSON payload lookup)",
        },
        "venues": venues,
        "classification_shadow": {
            "sample_target_per_rule_venue_trade_mode": 50,
            "accounting": (
                "PAPER_OUTCOME.realized_pnl is already net of recorded fees; "
                "do not subtract fees again."
            ),
            "by_venue": {
                venue: report.get("classification_shadow", {})
                for venue, report in venues.items()
                if isinstance(report, dict) and report.get("classification_shadow")
            },
        },
        "net_floor_sample_progress": {
            "sample_target_per_venue_and_trade_mode": 50,
            "by_venue": {
                venue: report.get("net_floor_sample_progress", {})
                for venue, report in venues.items()
                if isinstance(report, dict) and report.get("net_floor_sample_progress")
            },
        },
        "safety": "READ_ONLY_DIAGNOSTICS_NO_STRATEGY_OR_EXECUTION_CHANGES",
        "capture_read_policy": "ONLY_ENTRY_CAPTURES_REFERENCED_BY_WINDOWED_CLOSED_OUTCOMES",
    }


def _emit_linked_entry_outcome_forensics_logs(payload: Mapping[str, Any]) -> None:
    """Emit bounded, independently readable log records instead of one huge JSON line."""
    headline = {
        key: payload.get(key)
        for key in (
            "available",
            "mode",
            "window_days",
            "window_start_utc",
            "window_end_utc",
            "generated_at_utc",
            "join_keys",
            "capture_read_policy",
            "safety",
        )
    }
    _legacy.logger.warning(
        "[PAPER-FORENSICS-HEADLINE] %s",
        json.dumps(headline, ensure_ascii=False, separators=(",", ":")),
    )

    for venue in ("MAIN", "BYBIT", "OKX"):
        report = payload.get("venues", {}).get(venue)
        if not isinstance(report, dict):
            continue
        coverage = report.get("coverage")
        overall = report.get("overall")
        if coverage is None:
            _legacy.logger.warning(
                "[PAPER-FORENSICS-UNAVAILABLE] %s %s",
                venue,
                json.dumps(report, ensure_ascii=False, separators=(",", ":")),
            )
            continue

        _legacy.logger.warning(
            "[PAPER-FORENSICS-VENUE] %s %s",
            venue,
            json.dumps(
                {"venue": venue, "coverage": coverage, "overall": overall},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        )

        for mode, stats in sorted((report.get("by_trade_mode") or {}).items()):
            _legacy.logger.warning(
                "[PAPER-FORENSICS-MODE] %s %s",
                venue,
                json.dumps(
                    {"venue": venue, "trade_mode": mode, "stats": stats},
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            )

        net_floor_progress = report.get("net_floor_sample_progress") or {}
        for mode, cohort in sorted((net_floor_progress.get("cohorts") or {}).items()):
            _legacy.logger.warning(
                "[PAPER-NET-FLOOR-SAMPLE-PROGRESS] %s %s",
                venue,
                json.dumps(
                    {
                        "venue": venue,
                        "trade_mode": mode,
                        "sample_target": cohort.get("sample_target"),
                        "completed": cohort.get("completed"),
                        "remaining": cohort.get("remaining"),
                        "valid_unique_closed_positions": cohort.get("valid_unique_closed_positions"),
                        "excluded_positions": cohort.get("excluded_positions"),
                        "exclusion_reasons": cohort.get("exclusion_reasons"),
                        "by_status": cohort.get("by_status"),
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            )

        classification_shadow = report.get("classification_shadow") or {}
        for rule_name, rule in sorted((classification_shadow.get("rules") or {}).items()):
            for mode, cohort in sorted((rule.get("by_trade_mode") or {}).items()):
                _legacy.logger.warning(
                    "[PAPER-CLASSIFICATION-SHADOW-PROGRESS] %s %s",
                    venue,
                    json.dumps(
                        {
                            "venue": venue,
                            "rule": rule_name,
                            "trade_mode": mode,
                            "applicable": cohort.get("applicable"),
                            "sample_target": cohort.get("sample_target"),
                            "completed": cohort.get("completed"),
                            "remaining": cohort.get("remaining"),
                            "valid_unique_closed_positions": cohort.get("valid_unique_closed_positions"),
                            "excluded_positions": cohort.get("excluded_positions"),
                            "exclusion_reasons": cohort.get("exclusion_reasons"),
                            "by_classification": cohort.get("by_classification"),
                            "sample_rows_returned": len(cohort.get("samples") or []),
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                )

        for dimension in (
            "by_trade_mode_and_failed_gate",
            "by_trade_mode_and_score_band",
            "by_trade_mode_and_market_regime",
            "by_trade_mode_and_symbol_regime",
            "by_trade_mode_and_mtf_bias",
            "by_trade_mode_and_mtf_net_band",
            "by_trade_mode_and_volume_band",
            "by_trade_mode_and_rsi5m_band",
            "by_trade_mode_and_decision_evidence_source",
            "by_trade_mode_and_peak_gain_band",
            "by_trade_mode_and_paper_profit_protection",
            "by_trade_mode_and_profit_protection_shadow_status",
        ):
            groups = report.get(dimension) or {}
            for mode, members in sorted(groups.items()):
                for label, stats in sorted(members.items()):
                    _legacy.logger.warning(
                        "[PAPER-FORENSICS-SEGMENT] %s %s",
                        venue,
                        json.dumps(
                            {
                                "venue": venue,
                                "dimension": dimension,
                                "trade_mode": mode,
                                "segment": label,
                                "stats": stats,
                            },
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                    )

        for dimension in (
            "by_close_reason",
            "by_paper_profit_protection_triggered",
            "by_entry_v2_shadow_approval",
            "by_market_regime_source",
        ):
            groups = report.get(dimension) or {}
            for label, stats in sorted(groups.items()):
                _legacy.logger.warning(
                    "[PAPER-FORENSICS-CROSSCHECK] %s %s",
                    venue,
                    json.dumps(
                        {
                            "venue": venue,
                            "dimension": dimension,
                            "segment": label,
                            "stats": stats,
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                )

        for sample_name in ("worst_trades", "best_trades", "losers_with_positive_net_favorable_excursion"):
            samples = report.get(sample_name) or []
            for index, sample in enumerate(samples, start=1):
                _legacy.logger.info(
                    "[PAPER-FORENSICS-SAMPLE] %s %s",
                    venue,
                    json.dumps(
                        {
                            "venue": venue,
                            "sample_type": sample_name,
                            "rank": index,
                            "trade": sample,
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                )


def _emit_linked_entry_outcome_forensics() -> None:
    try:
        payload = _build_linked_entry_outcome_forensics()
        _emit_linked_entry_outcome_forensics_logs(payload)
    except Exception:
        _legacy.logger.exception("Paper linked entry/outcome forensics emission failed")


def _start_linked_entry_outcome_forensics() -> None:
    """Run one bounded, read-only forensic snapshot after hosted labs start."""
    global _PAPER_FORENSICS_STARTED
    with _PAPER_FORENSICS_START_LOCK:
        if _PAPER_FORENSICS_STARTED:
            return
        _PAPER_FORENSICS_STARTED = True
    threading.Thread(
        target=_emit_linked_entry_outcome_forensics,
        daemon=True,
        name="paper-linked-entry-outcome-forensics",
    ).start()


@app.get("/paper/forensic-entry-outcomes")
def _paper_forensic_entry_outcomes():
    """Read-only joined evidence for MAIN, Bybit and OKX closed Paper trades."""
    payload = _build_linked_entry_outcome_forensics()
    status_code = 200 if payload.get("available") else 503
    _emit_linked_entry_outcome_forensics_logs(payload)
    return jsonify(payload), status_code


@app.get("/paper/precalibration-shadow-report")
def _paper_precalibration_shadow_report():
    """Read-only outcomes for prior-formula Scalp candidates that pass current downstream gates."""
    store = _paper_precalibration_shadow_store
    if store is None:
        return jsonify({
            "available": False,
            "mode": "PAPER_ONLY",
            "reason": "PRECALIBRATION_SHADOW_TRACKER_DISABLED_OR_POSTGRES_UNAVAILABLE",
        }), 503
    try:
        records = store.read_all()
        if getattr(store, "last_error", None):
            raise RuntimeError("PRECALIBRATION_SHADOW_READ_FAILED")
        payload = build_precalibration_shadow_report(records)
        payload["generated_at_utc"] = datetime.now(timezone.utc).isoformat()
        payload["persistent_store"] = store.summary()
        _legacy.logger.info(
            "[PAPER-PRECALIBRATION-SHADOW-REPORT] %s",
            json.dumps({
                "unique_candidate_count": payload["unique_candidate_count"],
                "watch_started": payload["watch_started"],
                "watch_active": payload["watch_active"],
                "watch_completed": payload["watch_completed"],
                "dispositions": payload["dispositions"],
                "outcomes": payload["outcomes"],
                "decisive_outcomes": payload["decisive_outcomes"],
                "sample_progress": {
                    key: value for key, value in payload["sample_progress"].items()
                    if key != "samples"
                },
                "net_profit_factor_after_estimated_fees": payload["net_profit_factor_after_estimated_fees"],
            }, ensure_ascii=False, separators=(",", ":")),
        )
        return jsonify(payload), 200
    except Exception as exc:
        _legacy.logger.exception("Pre-calibration Paper shadow report failed")
        return jsonify({
            "available": False,
            "mode": "PAPER_ONLY",
            "reason": "PRECALIBRATION_SHADOW_READ_FAILED",
            "error": type(exc).__name__,
        }), 503


@app.get("/paper/blocked-entry-shadow-report")
def _paper_blocked_entry_shadow_report():
    """Read-only counterfactual outcomes for the existing MAIN/SCALP Paper veto."""
    store = _paper_blocked_entry_shadow_store
    if store is None:
        return jsonify({
            "available": False,
            "mode": "PAPER_ONLY",
            "reason": "BLOCKED_ENTRY_SHADOW_TRACKER_DISABLED_OR_POSTGRES_UNAVAILABLE",
        }), 503
    try:
        records = store.read_all()
        if getattr(store, "last_error", None):
            raise RuntimeError("BLOCKED_ENTRY_SHADOW_READ_FAILED")
        starts = {
            str(row.get("source_capture_id") or ""): row
            for row in records
            if isinstance(row, dict) and row.get("record_type") == "START"
        }
        finals = [
            row for row in records
            if isinstance(row, dict) and row.get("record_type") == "FINAL"
        ]
        final_ids = {
            str(row.get("source_capture_id") or "")
            for row in finals
        }
        active = [
            row for key, row in starts.items()
            if key and key not in final_ids and str(row.get("status") or "") == "OBSERVING"
        ]
        final_by_id = {
            str(row.get("source_capture_id") or ""): row
            for row in finals
            if str(row.get("source_capture_id") or "")
        }
        unique_finals = list(final_by_id.values())
        counts = {}
        exclusions = {}
        decisive_statuses = {"TARGET_HIT", "STOP_HIT", "TIME_LIMIT_EXIT"}
        valid_finals = []
        for row in unique_finals:
            status = str(row.get("status") or "UNKNOWN").upper()
            counts[status] = counts.get(status, 0) + 1
            net_value = row.get("net_return_percent_after_estimated_fees")
            try:
                net_value = float(net_value) if net_value is not None else None
            except (TypeError, ValueError, OverflowError):
                net_value = None
            if status not in decisive_statuses:
                reason = status or "UNKNOWN"
                exclusions[reason] = exclusions.get(reason, 0) + 1
            elif net_value is None:
                exclusions["NET_RETURN_UNAVAILABLE"] = exclusions.get("NET_RETURN_UNAVAILABLE", 0) + 1
            else:
                valid_finals.append((row, net_value))
        sample_progress = {
            "venue": "MAIN",
            "market_data_source": "BINANCE",
            "trade_mode": "SCALP",
            "sample_target": 50,
            "completed": min(len(valid_finals), 50),
            "remaining": max(0, 50 - len(valid_finals)),
            "valid_unique_completed_watches": len(valid_finals),
            "additional_valid_watches_beyond_target": max(0, len(valid_finals) - 50),
            "pending_incomplete_watches": len(active),
            "excluded_final_records": sum(exclusions.values()),
            "exclusion_reasons": dict(sorted(exclusions.items())),
            "samples": [
                {
                    "source_capture_id": row.get("source_capture_id"),
                    "symbol": str(row.get("symbol") or "UNKNOWN").upper(),
                    "status": str(row.get("status") or "UNKNOWN").upper(),
                    "net_return_percent_after_estimated_fees": net_value,
                    "completed_at_utc": row.get("completed_at_utc"),
                    "blocked_reason": row.get("blocked_reason"),
                }
                for row, net_value in sorted(
                    valid_finals,
                    key=lambda item: str(item[0].get("completed_at_utc") or ""),
                )[:50]
            ],
        }
        payload = {
            "available": True,
            "mode": "PAPER_ONLY",
            "trial_name": _BLOCKED_ENTRY_SHADOW_TRIAL_NAME,
            "start_records": len(starts),
            "completed_records": len(finals),
            "active_records": len(active),
            "completed_by_status": counts,
            "sample_progress": sample_progress,
            "active": active,
            "recent_completed": finals[-50:],
            "model": {
                "path_source": "BINANCE_RELAY_WEBSOCKET_CLOSED_5M_CANDLES",
                "stop_target_source": "ENTRY_V2_CAPTURE",
                "horizon_closed_5m_bars": 24,
                "estimated_round_trip_fees": "2 x configured Paper fee rate",
                "spread_and_slippage": "NOT_INCLUDED",
                "same_candle_stop_and_target": "AMBIGUOUS_NOT_COUNTED_AS_WIN_OR_LOSS",
                "no_paper_positions_or_orders_are_created": True,
            },
        }
        _legacy.logger.info(
            "[PAPER-BLOCKED-ENTRY-SHADOW-REPORT] %s",
            json.dumps({
                "start_records": payload["start_records"],
                "completed_records": payload["completed_records"],
                "active_records": payload["active_records"],
                "completed_by_status": counts,
                "sample_progress": {
                    key: value for key, value in sample_progress.items()
                    if key != "samples"
                },
            }, ensure_ascii=False, separators=(",", ":")),
        )
        return jsonify(payload), 200
    except Exception as exc:
        _legacy.logger.exception("Blocked-entry Paper shadow report failed")
        return jsonify({
            "available": False,
            "mode": "PAPER_ONLY",
            "reason": "BLOCKED_ENTRY_SHADOW_READ_FAILED",
            "error": type(exc).__name__,
        }), 503




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


def _binance_rest_candles_for_compare(
    symbol: str,
    interval: str,
) -> tuple[list[dict], float | None]:
    """Read an existing cached REST snapshot without issuing a REST request.

    The main relay/WebSocket mode deliberately avoids a cold-start REST seed
    so it does not create a request burst against an IP already rate-limited by
    Binance. When no cached REST snapshot exists, the comparator must report
    that limitation rather than calling the REST window empty.
    """
    manager = getattr(_legacy, "market_data_manager", None)
    cache = getattr(manager, "cache", None)
    if manager is None or cache is None:
        return [], None

    upper_symbol = str(symbol).upper()
    interval_name = str(interval)
    limit = 150 if interval_name == "15m" else 60
    key = f"{interval_name}:{upper_symbol}:{limit}"

    try:
        # Diagnostic comparison must inspect the available cache snapshot even
        # when its normal entry TTL has expired. The snapshot timestamp is then
        # used by compare_rest_ws_candle() to distinguish a pre-close snapshot
        # from a valid historical closed-candle comparison.
        snapshot = cache.get(key)
        from core.binance_rest_ws_comparison import normalize_cached_rest_snapshot
        return normalize_cached_rest_snapshot(snapshot)
    except Exception:
        return [], None


def _binance_rest_ws_compare_once(symbol: str, interval: str) -> None:
    global _binance_rest_ws_last_comparison
    stream = globals().get("_binance_market_stream")
    if stream is None or not callable(getattr(stream, "get_latest_kline", None)):
        return

    try:
        rest_candles, rest_snapshot_fetched_at = _binance_rest_candles_for_compare(symbol, interval)
        get_closed = getattr(stream, "get_latest_closed_kline", None)
        ws_candle = get_closed(symbol, interval) if callable(get_closed) else stream.get_latest_kline(symbol, interval)
        result = compare_rest_ws_candle(
            rest_candles,
            ws_candle,
            rest_snapshot_fetched_at=rest_snapshot_fetched_at,
            rest_snapshot_available=(
                rest_snapshot_fetched_at is not None or bool(rest_candles)
            ),
        )
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
        if result.get("status") == "DIVERGENCE":
            _legacy.logger.info(
                "[BINANCE-REST-WS-COMPARE-DIFF] symbol=%s interval=%s field_abs_diff=%s "
                "rest_snapshot_fetched_at=%s ws_close_time=%s",
                result.get("symbol"),
                result.get("interval"),
                result.get("field_abs_diff"),
                result.get("rest_snapshot_fetched_at"),
                result.get("ws_close_time"),
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


def _selected_venue_websocket_snapshot() -> tuple[str, dict[str, object]]:
    """Return health for the configured venue only; never substitute Binance in a lab."""
    mode = str(globals().get("PAPER_VENUE_MODE", "MIXED") or "MIXED").upper()
    venue, stream_name = {
        "OKX_ONLY_LAB": ("OKX", "_okx_market_stream"),
        "BYBIT_ONLY_LAB": ("BYBIT", "_bybit_market_stream"),
        "BINANCE_ONLY_LAB": ("BINANCE", "_binance_market_stream"),
        "MIXED": ("BINANCE", "_binance_market_stream"),
    }.get(mode, ("UNKNOWN", ""))

    stream = globals().get(stream_name) if stream_name else None
    snapshot_method = getattr(stream, "snapshot", None)
    if not callable(snapshot_method):
        return venue, {
            "available": False,
            "connected": False,
            "event_stream_healthy": False,
            "venue_mode": mode,
            "reason": "SELECTED_VENUE_STREAM_UNAVAILABLE",
        }
    snapshot = snapshot_method()
    return venue, dict(snapshot) if isinstance(snapshot, dict) else {
        "available": False,
        "connected": False,
        "event_stream_healthy": False,
        "venue_mode": mode,
        "reason": "INVALID_HEALTH_SNAPSHOT",
    }


def _venue_websocket_health_loop() -> None:
    while True:
        try:
            venue, snapshot = _selected_venue_websocket_snapshot()
            if venue == "OKX":
                _legacy.logger.info(
                    "[OKX-WS-HEALTH] connected=%s public_connected=%s business_connected=%s "
                    "healthy=%s streams=%s kline_coverage=%s/%s ticker_coverage=%s/%s "
                    "events=%s closed_kline=%s reconnects=%s parse_errors=%s "
                    "last_event_age=%s last_error=%s",
                    snapshot.get("connected"),
                    snapshot.get("public_connected"),
                    snapshot.get("business_connected"),
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
                    snapshot.get("last_event_age_seconds"),
                    snapshot.get("last_error"),
                )
            else:
                _legacy.logger.info(
                    "[%s-WS-HEALTH] mode=%s transport=%s available=%s connected=%s healthy=%s streams=%s "
                    "kline_coverage=%s/%s kline_by_interval=%s missing_kline=%s "
                    "ticker_coverage=%s/%s missing_tickers=%s events=%s closed_kline=%s "
                    "reconnects=%s parse_errors=%s last_event_age=%s last_error=%s",
                    venue,
                    snapshot.get("venue_mode", globals().get("PAPER_VENUE_MODE", "MIXED")),
                    snapshot.get("transport", "BINANCE_DIRECT" if venue == "BINANCE" else "NATIVE"),
                    snapshot.get("available", True),
                    snapshot.get("connected"),
                    snapshot.get("event_stream_healthy"),
                    snapshot.get("stream_count"),
                    snapshot.get("symbols_with_latest_kline"),
                    snapshot.get("expected_kline_streams"),
                    snapshot.get("kline_coverage_by_interval", {}),
                    snapshot.get("missing_kline_series", [])[:8],
                    snapshot.get("tickers_with_latest"),
                    snapshot.get("expected_tickers"),
                    snapshot.get("missing_ticker_symbols", [])[:8],
                    snapshot.get("events_total"),
                    snapshot.get("closed_kline_events"),
                    snapshot.get("reconnects"),
                    snapshot.get("parse_errors"),
                    snapshot.get("last_event_age_seconds"),
                    snapshot.get("last_error"),
                )
        except Exception:
            _legacy.logger.exception("Selected venue WebSocket health logger failed")
        time.sleep(60.0)


# Backward-compatible name for existing imports/tests.
def _binance_websocket_health_loop() -> None:
    _venue_websocket_health_loop()


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
    _start_linked_entry_outcome_forensics()
    threading.Thread(target=_legacy._daily_report_loop, daemon=True, name="paper-daily-report").start()
    threading.Thread(target=_hosted_lab_daily_report_loop, daemon=True, name="hosted-lab-daily-reports").start()
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
        target=_venue_websocket_health_loop,
        daemon=True,
        name="venue-websocket-health",
    ).start()
    threading.Thread(
        target=_binance_rest_ws_compare_loop,
        daemon=True,
        name="binance-rest-ws-compare",
    ).start()
    _legacy.run_flask()