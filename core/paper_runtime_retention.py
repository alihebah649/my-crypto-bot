"""Safe bounded retention for durable MAIN Paper runtime history."""
from __future__ import annotations

import time
from typing import Any, MutableSet

PAPER_POSITION_RETENTION_SECONDS = 40.0 * 24.0 * 60.0 * 60.0
PAPER_ORDER_HISTORY_LIMIT = 1000

_TERMINAL_ORDER_STATUSES = {"FILLED", "REJECTED", "CANCELLED", "EXPIRED", "FAILED"}


def persist_or_confirm_paper_outcome(store: Any, record: dict[str, Any]) -> bool:
    """Return True only when a Paper outcome is known to exist durably.

    PostgresEvidenceStore.append() returns False both for an existing unique
    identity and for a failed write. Distinguish those cases with the existing
    indexed identity lookup; never mark an unconfirmed failed write as logged.
    """
    if store is None:
        return False
    position_id = str(record.get("position_id") or "").strip()
    if not position_id:
        return False

    append = getattr(store, "append", None)
    if not callable(append):
        return False
    try:
        if append(record):
            return True
        if getattr(store, "last_error", None):
            return False

        lookup = getattr(store, "get_by_identity", None)
        if not callable(lookup):
            return False
        existing = lookup(position_id)
        if getattr(store, "last_error", None):
            return False
        return (
            isinstance(existing, dict)
            and str(existing.get("position_id") or "") == position_id
        )
    except Exception:
        return False


def prune_main_paper_history(
    runtime: Any,
    evidence_store: Any,
    logged_position_ids: MutableSet[str],
    *,
    now_epoch: float | None = None,
    retention_seconds: float = PAPER_POSITION_RETENTION_SECONDS,
) -> list[str]:
    """Prune only old, durably evidenced, already-notified terminal positions.

    Forty days preserves the complete current UTC daily/weekly/monthly loss
    windows. A closed position is prunable only after both its outcome evidence
    is confirmed durable and its Telegram close notification is recorded sent.
    Active positions and closed positions with either condition missing remain.
    """
    if evidence_store is None:
        return []

    repository = getattr(runtime, "repository", None)
    get_closed = getattr(repository, "get_closed_positions", None)
    prune = getattr(repository, "prune_terminal_positions", None)
    if not callable(get_closed) or not callable(prune):
        return []

    now = time.time() if now_epoch is None else float(now_epoch)
    cutoff = now - max(0.0, float(retention_seconds))
    prunable_closed_ids: set[str] = set()
    for position in get_closed():
        position_id = str(getattr(position, "position_id", "") or "")
        if not position_id or position_id not in logged_position_ids:
            continue
        exit_metadata = getattr(position, "exit_metadata", {}) or {}
        if bool(exit_metadata.get("telegram_notification_sent")):
            prunable_closed_ids.add(position_id)

    removed = prune(
        older_than_epoch=cutoff,
        persisted_closed_ids=prunable_closed_ids,
    )
    if not removed:
        return []

    remaining_closed = list(get_closed())
    remaining_ids = {
        str(getattr(position, "position_id", "") or "")
        for position in remaining_closed
        if getattr(position, "position_id", None)
    }
    logged_position_ids.intersection_update(remaining_ids)

    ledger = getattr(runtime, "loss_ledger", None)
    sync = getattr(ledger, "sync", None)
    if callable(sync):
        sync(remaining_closed)
    return list(removed)


def compact_paper_order_history(
    adapter: Any,
    *,
    keep: int = PAPER_ORDER_HISTORY_LIMIT,
) -> int:
    """Keep recent completed Paper order results while preserving unresolved ones."""
    orders = getattr(adapter, "orders", None)
    if not isinstance(orders, dict):
        return 0
    limit = max(1, int(keep))
    if len(orders) <= limit:
        return 0

    items = list(orders.items())
    terminal_ids = []
    unresolved_ids = set()
    for order_id, result in items:
        status = getattr(result, "status", None)
        status_value = str(getattr(status, "value", status or "")).upper()
        if status_value in _TERMINAL_ORDER_STATUSES:
            terminal_ids.append(order_id)
        else:
            # Unknown and pending states are retained conservatively.
            unresolved_ids.add(order_id)

    retained_terminal_ids = set(terminal_ids[-limit:])
    retained = {
        order_id: result
        for order_id, result in items
        if order_id in unresolved_ids or order_id in retained_terminal_ids
    }
    removed = len(orders) - len(retained)
    if removed:
        orders.clear()
        orders.update(retained)
    return removed
