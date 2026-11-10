"""Runtime coordinator for paired ATR/structural Paper stop observations.

The coordinator is deliberately venue-scoped: each context owns its own
PositionRepository, market stream, and evidence store. It only marks
counterfactual paths and never calls the Paper execution adapter.
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from core.paper_structural_stop_comparison import (
    advance_structural_stop_comparison,
    build_structural_stop_comparison_decision,
    build_structural_stop_comparison_watch,
)

_ACTIVE_POSITION_STATES = {
    "OPEN",
    "HOLD",
    "REVIEW_REQUIRED",
    "PARTIALLY_CLOSED",
}


def _status(value: Any) -> str:
    return str(getattr(value, "name", value) or "").upper()


def _position_value(position: Any, name: str, default: Any = None) -> Any:
    if isinstance(position, Mapping):
        return position.get(name, default)
    return getattr(position, name, default)


class PaperStructuralStopComparisonCoordinator:
    """Coordinate multiple isolated venue repositories with one Paper loop."""

    def __init__(self, *, logger: logging.Logger | None = None) -> None:
        self._logger = logger or logging.getLogger(__name__)
        self._lock = threading.RLock()
        self._contexts: dict[str, dict[str, Any]] = {}
        self._active: dict[str, tuple[str, dict[str, Any]]] = {}

    @staticmethod
    def _watch_key(context_key: str, position_id: str) -> str:
        return f"{context_key}|{position_id}"

    def add_context(
        self,
        *,
        context_key: str,
        venue: str,
        venue_mode: str,
        repository: Any,
        stream: Any,
        runtime: Any,
        evidence_store: Any,
        entry_capture_store: Any = None,
        restore: bool = True,
    ) -> dict[str, Any]:
        """Register one venue's own Paper repository, stream and evidence."""
        key = str(context_key or "").strip().upper()
        if not key:
            raise ValueError("STRUCTURAL_STOP_CONTEXT_KEY_REQUIRED")
        context = {
            "context_key": key,
            "venue": str(venue or "UNKNOWN").upper(),
            "venue_mode": str(venue_mode or "UNKNOWN").upper(),
            "repository": repository,
            "stream": stream,
            "runtime": runtime,
            "store": evidence_store,
            "entry_capture_store": entry_capture_store,
            "existing_positions_seeded": False,
        }
        with self._lock:
            self._contexts[key] = context

        restored = 0
        if restore and evidence_store is not None:
            try:
                records = evidence_store.read_all()
                if getattr(evidence_store, "last_error", None):
                    raise RuntimeError("STRUCTURAL_STOP_CONTEXT_RESTORE_READ_FAILED")
                final_ids = {
                    str(row.get("position_id") or "").strip()
                    for row in records
                    if isinstance(row, Mapping) and row.get("record_type") == "FINAL"
                }
                for row in records:
                    if not isinstance(row, Mapping) or row.get("record_type") != "START":
                        continue
                    position_id = str(row.get("position_id") or "").strip()
                    state = _status(row.get("status"))
                    if (
                        not position_id
                        or position_id in final_ids
                        or state not in {"OBSERVING", "COMPLETE"}
                    ):
                        continue
                    watch_key = self._watch_key(key, position_id)
                    with self._lock:
                        self._active[watch_key] = (key, dict(row))
                    restored += 1
            except Exception:
                self._logger.exception(
                    "[PAPER-STRUCTURAL-STOP-COMPARISON] hosted restore failed context=%s",
                    key,
                )

        self._logger.info(
            "[PAPER-STRUCTURAL-STOP-COMPARISON] context_ready context=%s venue=%s venue_mode=%s restored=%d",
            key,
            context["venue"],
            context["venue_mode"],
            restored,
        )
        return {
            "context_key": key,
            "venue": context["venue"],
            "venue_mode": context["venue_mode"],
            "restored_active_positions": restored,
        }

    def _record_decision(
        self,
        context: Mapping[str, Any],
        position: Any,
        *,
        source_capture_id: str,
        reason: str,
    ) -> bool:
        store = context.get("store")
        position_id = str(_position_value(position, "position_id", "") or "").strip()
        if store is None or not position_id:
            return False
        decision = build_structural_stop_comparison_decision(
            position,
            source_capture_id=source_capture_id,
            venue=context["venue"],
            venue_mode=context["venue_mode"],
            reason=reason,
        )
        inserted = store.append(decision)
        if not inserted and getattr(store, "last_error", None):
            self._logger.error(
                "[PAPER-STRUCTURAL-STOP-COMPARISON] DECISION persistence failed context=%s position=%s error=%s",
                context["context_key"],
                position_id,
                store.last_error,
            )
            return False
        if inserted:
            self._logger.info(
                "[PAPER-STRUCTURAL-STOP-COMPARISON] DECISION context=%s %s",
                context["context_key"],
                decision,
            )
        return True

    def register_start(
        self,
        context_key: str,
        position: Any,
        capture: Mapping[str, Any],
        *,
        use_captured_atr_stop: bool = False,
    ) -> bool:
        """Persist the exact entry-time capture for a successfully opened Paper position."""
        key = str(context_key or "").strip().upper()
        with self._lock:
            context = self._contexts.get(key)
        if context is None:
            self._logger.error(
                "[PAPER-STRUCTURAL-STOP-COMPARISON] unknown context=%s",
                key,
            )
            return False
        store = context["store"]
        position_id = str(_position_value(position, "position_id", "") or "").strip()
        if store is None or not position_id:
            return False

        metadata = _position_value(position, "entry_metadata", {})
        metadata = metadata if isinstance(metadata, Mapping) else {}
        capture_id = str(
            metadata.get("entry_v2_shadow_capture_id")
            or metadata.get("entry_v2_capture_id")
            or (capture.get("capture_id") if isinstance(capture, Mapping) else "")
            or ""
        ).strip()
        captured_identity = (
            str(capture.get("capture_id") or "").strip()
            if isinstance(capture, Mapping) else ""
        )
        if not capture_id:
            self._record_decision(
                context,
                position,
                source_capture_id="",
                reason="ENTRY_V2_CAPTURE_ID_UNAVAILABLE",
            )
            return False
        if not captured_identity or captured_identity != capture_id:
            self._record_decision(
                context,
                position,
                source_capture_id=capture_id,
                reason="EXACT_ENTRY_V2_CAPTURE_NOT_FOUND",
            )
            return False

        watch_position = position
        if use_captured_atr_stop:
            # A pre-existing Paper position may already have had its live
            # stop moved by the Trade Manager. For safe backfill, do not treat
            # that later stop as the initial ATR stop; use the immutable ATR
            # stop captured at entry instead.
            watch_position = {
                "position_id": position_id,
                "symbol": _position_value(position, "symbol", ""),
                "entry_price": _position_value(position, "entry_price"),
                "stop_loss": None,
                "trade_mode": metadata.get("trade_mode", "UNKNOWN"),
                "status": _position_value(position, "status", ""),
                "entry_metadata": dict(metadata),
            }

        try:
            fee_rate = float(
                getattr(
                    getattr(context["runtime"], "execution_adapter", None),
                    "fee_rate",
                    0.001,
                )
                or 0.001
            )
            watch = build_structural_stop_comparison_watch(
                capture,
                watch_position,
                fee_rate=fee_rate,
                venue=context["venue"],
                venue_mode=context["venue_mode"],
            )
        except (TypeError, ValueError) as exc:
            self._record_decision(
                context,
                position,
                source_capture_id=capture_id,
                reason=str(exc) or type(exc).__name__,
            )
            return False

        inserted = store.append(watch)
        if not inserted and getattr(store, "last_error", None):
            self._logger.error(
                "[PAPER-STRUCTURAL-STOP-COMPARISON] START persistence failed context=%s position=%s error=%s",
                key,
                position_id,
                store.last_error,
            )
            return False

        watch_key = self._watch_key(key, position_id)
        with self._lock:
            self._active[watch_key] = (key, dict(watch))
        self._logger.info(
            "[PAPER-STRUCTURAL-STOP-COMPARISON] START context=%s %s",
            key,
            watch,
        )
        return True

    @staticmethod
    def _capture_time_ms(capture: Mapping[str, Any]) -> int | None:
        value = capture.get("captured_at")
        if isinstance(value, (int, float)):
            timestamp = float(value)
            return int(timestamp if timestamp > 10_000_000_000 else timestamp * 1000)
        raw = str(value or "").strip()
        if not raw:
            return None
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return int(parsed.timestamp() * 1000)
        except (TypeError, ValueError, OverflowError):
            return None

    def seed_existing_open_positions(self, context_key: str) -> dict[str, Any]:
        """Seed only pre-existing open positions with exact captures and entry-bar coverage.

        This is deliberately bounded by the selected venue stream's local 60-bar
        5m buffer. Positions older than that buffer are recorded as unmeasurable
        rather than assigned a fabricated stop-path result.
        """
        key = str(context_key or "").strip().upper()
        with self._lock:
            context = self._contexts.get(key)
            if context is None:
                return {"context_key": key, "available": False, "reason": "CONTEXT_NOT_FOUND"}
            if context.get("existing_positions_seeded"):
                return {
                    "context_key": key,
                    "available": True,
                    "already_seeded": True,
                    "started": 0,
                    "skipped": 0,
                    "skip_reasons": {},
                }
            # Set the one-shot guard before reading; a transient storage error
            # is surfaced in the result and does not create repeated writes.
            context["existing_positions_seeded"] = True

        repository = context.get("repository")
        capture_store = context.get("entry_capture_store")
        stream = context.get("stream")
        get_positions = getattr(repository, "get_open_positions", None)
        if not callable(get_positions):
            return {"context_key": key, "available": False, "reason": "OPEN_POSITION_LOOKUP_UNAVAILABLE"}
        try:
            positions = list(get_positions() or [])
        except Exception:
            self._logger.exception(
                "[PAPER-STRUCTURAL-STOP-COMPARISON] hosted open-position backfill read failed context=%s",
                key,
            )
            return {"context_key": key, "available": False, "reason": "OPEN_POSITION_READ_FAILED"}

        lookup = getattr(capture_store, "get_by_identity", None)
        get_history = getattr(stream, "get_kline_history", None)
        started = 0
        skipped = 0
        skip_reasons: dict[str, int] = {}
        for position in positions:
            position_id = str(_position_value(position, "position_id", "") or "").strip()
            if not position_id:
                skipped += 1
                skip_reasons["POSITION_ID_UNAVAILABLE"] = skip_reasons.get("POSITION_ID_UNAVAILABLE", 0) + 1
                continue

            watch_key = self._watch_key(key, position_id)
            with self._lock:
                if watch_key in self._active:
                    continue

            metadata = _position_value(position, "entry_metadata", {})
            metadata = metadata if isinstance(metadata, Mapping) else {}
            capture_id = str(
                metadata.get("entry_v2_shadow_capture_id")
                or metadata.get("entry_v2_capture_id")
                or ""
            ).strip()
            if not capture_id:
                reason = "ENTRY_V2_CAPTURE_ID_UNAVAILABLE"
                self._record_decision(context, position, source_capture_id="", reason=reason)
                skipped += 1
                skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
                continue

            if not callable(lookup):
                reason = "ENTRY_V2_CAPTURE_LOOKUP_UNAVAILABLE"
                self._record_decision(context, position, source_capture_id=capture_id, reason=reason)
                skipped += 1
                skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
                continue
            try:
                capture = lookup(capture_id)
            except Exception:
                self._logger.exception(
                    "[PAPER-STRUCTURAL-STOP-COMPARISON] hosted entry capture lookup failed context=%s position=%s",
                    key,
                    position_id,
                )
                capture = None
            if not isinstance(capture, Mapping) or str(capture.get("capture_id") or "").strip() != capture_id:
                reason = "EXACT_ENTRY_V2_CAPTURE_NOT_FOUND"
                self._record_decision(context, position, source_capture_id=capture_id, reason=reason)
                skipped += 1
                skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
                continue

            captured_at_ms = self._capture_time_ms(capture)
            if captured_at_ms is None:
                reason = "ENTRY_CAPTURE_TIMESTAMP_UNAVAILABLE"
                self._record_decision(context, position, source_capture_id=capture_id, reason=reason)
                skipped += 1
                skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
                continue

            if not callable(get_history):
                reason = "VENUE_5M_HISTORY_UNAVAILABLE"
                self._record_decision(context, position, source_capture_id=capture_id, reason=reason)
                skipped += 1
                skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
                continue
            try:
                candles = get_history(str(_position_value(position, "symbol", "") or ""), "5m", 60) or []
            except Exception:
                self._logger.exception(
                    "[PAPER-STRUCTURAL-STOP-COMPARISON] hosted 5m history read failed context=%s position=%s",
                    key,
                    position_id,
                )
                candles = []
            open_times = [
                int(float(row.get("open_time")))
                for row in candles
                if isinstance(row, Mapping) and row.get("open_time") is not None
            ]
            entry_bar_open = captured_at_ms // (5 * 60 * 1000) * (5 * 60 * 1000)
            if not open_times:
                reason = "VENUE_5M_HISTORY_NOT_READY"
            elif min(open_times) > entry_bar_open:
                reason = "HISTORICAL_5M_BUFFER_DOES_NOT_COVER_ENTRY"
            else:
                reason = ""
            if reason:
                self._record_decision(context, position, source_capture_id=capture_id, reason=reason)
                skipped += 1
                skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
                continue

            if self.register_start(
                key,
                position,
                capture,
                use_captured_atr_stop=True,
            ):
                started += 1
            else:
                skipped += 1
                reason = "ENTRY_CAPTURE_OR_STOP_CONTEXT_UNMEASURABLE"
                skip_reasons[reason] = skip_reasons.get(reason, 0) + 1

        result = {
            "context_key": key,
            "available": True,
            "existing_open_positions_seen": len(positions),
            "started": started,
            "skipped": skipped,
            "skip_reasons": skip_reasons,
        }
        self._logger.info(
            "[PAPER-STRUCTURAL-STOP-COMPARISON] existing_positions_seeded context=%s summary=%s",
            key,
            result,
        )
        return result

    def _actual_paper_outcome(self, context: Mapping[str, Any], position_id: str) -> dict[str, Any] | None:
        repository = context.get("repository")
        getter = getattr(repository, "get", None)
        if not callable(getter):
            return None
        try:
            position = getter(position_id)
        except Exception:
            return None
        if position is None:
            return None

        status = _status(_position_value(position, "status", ""))
        if status in _ACTIVE_POSITION_STATES:
            return {"status": status}
        if status != "CLOSED":
            return {"status": status or "UNKNOWN"}

        exit_metadata = _position_value(position, "exit_metadata", {})
        exit_metadata = exit_metadata if isinstance(exit_metadata, Mapping) else {}
        return {
            "status": "CLOSED",
            "realized_pnl": float(_position_value(position, "realized_pnl", 0.0) or 0.0),
            "total_fees": float(_position_value(position, "total_fees", 0.0) or 0.0),
            "exit_price": exit_metadata.get(
                "exit_price",
                _position_value(position, "current_price"),
            ),
            "exit_reason": exit_metadata.get("exit_reason") or exit_metadata.get("reason") or "",
        }

    def advance(self) -> int:
        """Advance all venue-specific price paths; persist only changed checkpoints."""
        with self._lock:
            items = list(self._active.items())
            contexts = dict(self._contexts)

        changed_count = 0
        for watch_key, (context_key, previous) in items:
            context = contexts.get(context_key)
            if context is None:
                continue
            updated = dict(previous)
            state_changed = False
            position_id = str(updated.get("position_id") or "").strip()

            if _status(updated.get("status")) == "OBSERVING":
                stream = context.get("stream")
                get_history = getattr(stream, "get_kline_history", None)
                if not callable(get_history):
                    continue
                try:
                    candles = get_history(str(updated.get("symbol") or ""), "5m", 60) or []
                    updated, state_changed = advance_structural_stop_comparison(previous, candles)
                except Exception:
                    self._logger.exception(
                        "[PAPER-STRUCTURAL-STOP-COMPARISON] path update failed context=%s position=%s",
                        context_key,
                        position_id,
                    )
                    continue

            actual_outcome = self._actual_paper_outcome(context, position_id)
            if actual_outcome is not None and updated.get("actual_paper_outcome") != actual_outcome:
                updated["actual_paper_outcome"] = actual_outcome
                state_changed = True

            actual_status = (
                _status(actual_outcome.get("status"))
                if isinstance(actual_outcome, Mapping)
                else "NOT_FOUND"
            )
            actual_still_open = actual_status in _ACTIVE_POSITION_STATES
            paths_complete = _status(updated.get("status")) in {
                "COMPLETE",
                "UNMEASURABLE_CONTEXT",
            }

            # A finished shadow pair waits for the real Paper position close.
            # This avoids reporting an unrealized Paper outcome as if it were final.
            if not paths_complete or actual_still_open:
                if state_changed:
                    store = context["store"]
                    try:
                        persisted = store.upsert(updated)
                        if not persisted and getattr(store, "last_error", None):
                            raise RuntimeError("STRUCTURAL_STOP_COMPARISON_CHECKPOINT_FAILED")
                        changed_count += 1
                    except Exception:
                        self._logger.exception(
                            "[PAPER-STRUCTURAL-STOP-COMPARISON] checkpoint failed context=%s position=%s",
                            context_key,
                            position_id,
                        )
                with self._lock:
                    if watch_key in self._active:
                        self._active[watch_key] = (context_key, updated)
                continue

            final_event = dict(updated)
            final_event["record_type"] = "FINAL"
            final_event["record_id"] = f"{position_id}:FINAL"
            final_event["capture_id"] = f"{position_id}:FINAL"
            store = context["store"]
            try:
                inserted = store.append(final_event)
                if not inserted and getattr(store, "last_error", None):
                    raise RuntimeError("STRUCTURAL_STOP_COMPARISON_FINAL_PERSIST_FAILED")
                with self._lock:
                    self._active.pop(watch_key, None)
                changed_count += 1
                if inserted:
                    self._logger.info(
                        "[PAPER-STRUCTURAL-STOP-COMPARISON] FINAL context=%s %s",
                        context_key,
                        final_event,
                    )
            except Exception:
                with self._lock:
                    self._active[watch_key] = (context_key, final_event)
                self._logger.exception(
                    "[PAPER-STRUCTURAL-STOP-COMPARISON] FINAL persistence failed context=%s position=%s",
                    context_key,
                    position_id,
                )
        return changed_count

    def read_all_records(self) -> list[dict[str, Any]]:
        """Return comparison evidence from all registered venue-specific stores."""
        with self._lock:
            contexts = list(self._contexts.values())
        records: list[dict[str, Any]] = []
        for context in contexts:
            store = context.get("store")
            if store is None:
                continue
            rows = store.read_all()
            if getattr(store, "last_error", None):
                raise RuntimeError(
                    f"STRUCTURAL_STOP_COMPARISON_REPORT_READ_FAILED:{context['context_key']}"
                )
            records.extend(dict(row) for row in rows if isinstance(row, Mapping))
        return records

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            contexts = list(self._contexts.values())
            active = list(self._active.values())
        active_by_context: dict[str, int] = {}
        complete_waiting: dict[str, int] = {}
        for context_key, watch in active:
            active_by_context[context_key] = active_by_context.get(context_key, 0) + 1
            if (
                _status(watch.get("status")) == "COMPLETE"
                and _status((watch.get("actual_paper_outcome") or {}).get("status")) != "CLOSED"
            ):
                complete_waiting[context_key] = complete_waiting.get(context_key, 0) + 1
        return {
            "available": True,
            "mode": "PAPER_ONLY",
            "contexts": {
                context["context_key"]: {
                    "venue": context["venue"],
                    "venue_mode": context["venue_mode"],
                    "active_positions": active_by_context.get(context["context_key"], 0),
                    "shadow_paths_complete_waiting_for_actual_close": complete_waiting.get(context["context_key"], 0),
                }
                for context in contexts
            },
            "active_positions": len(active),
            "shadow_paths_complete_waiting_for_actual_close": sum(complete_waiting.values()),
            "trading_logic_changed": False,
        }


__all__ = ["PaperStructuralStopComparisonCoordinator"]
