"""Runtime coordinator for paired ATR/structural Paper stop observations.

The coordinator is deliberately venue-scoped: each context owns its own
PositionRepository, market stream, and evidence store. It only marks
counterfactual paths and never calls the Paper execution adapter.
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Mapping
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

    def register_start(
        self,
        context_key: str,
        position: Any,
        capture: Mapping[str, Any],
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
                position,
                fee_rate=fee_rate,
                venue=context["venue"],
                venue_mode=context["venue_mode"],
            )
        except (TypeError, ValueError) as exc:
            decision = build_structural_stop_comparison_decision(
                position,
                source_capture_id=capture_id,
                venue=context["venue"],
                venue_mode=context["venue_mode"],
                reason=str(exc) or type(exc).__name__,
            )
            inserted = store.append(decision)
            if not inserted and getattr(store, "last_error", None):
                self._logger.error(
                    "[PAPER-STRUCTURAL-STOP-COMPARISON] DECISION persistence failed context=%s position=%s error=%s",
                    key,
                    position_id,
                    store.last_error,
                )
            else:
                self._logger.info(
                    "[PAPER-STRUCTURAL-STOP-COMPARISON] DECISION context=%s %s",
                    key,
                    decision,
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
