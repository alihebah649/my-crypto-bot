"""Low-allocation, read-only diagnostics for Paper runtime memory investigations."""
from __future__ import annotations

import gc
import os
import threading
from datetime import datetime, timezone
from typing import Any


def _current_rss_bytes(statm_path: str = "/proc/self/statm") -> int | None:
    """Read resident pages from procfs without a third-party dependency."""
    try:
        with open(statm_path, "r", encoding="ascii") as handle:
            fields = handle.read().split()
        if len(fields) < 2:
            return None
        resident_pages = int(fields[1])
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
        if resident_pages < 0 or page_size <= 0:
            return None
        return resident_pages * page_size
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def _safe_len(value: Any) -> int | None:
    try:
        return len(value)
    except (TypeError, AttributeError):
        return None


def build_paper_runtime_memory_snapshot(
    runtime: Any,
    *,
    statm_path: str = "/proc/self/statm",
) -> dict[str, Any]:
    """Summarize long-lived in-process collections without copying their contents.

    This function deliberately avoids get_all(), get_closed_positions(),
    evidence read_all(), and serialization of orders or positions.
    """
    repository = getattr(runtime, "repository", None)
    status_counts: dict[str, int] = {}
    count_statuses = getattr(repository, "status_counts", None)
    if callable(count_statuses):
        raw_counts = count_statuses()
        if isinstance(raw_counts, dict):
            status_counts = {
                str(key): max(0, int(value))
                for key, value in raw_counts.items()
            }

    adapter = getattr(runtime, "execution_adapter", None)
    orders = getattr(adapter, "orders", None)
    diagnostics = getattr(runtime, "last_entry_diagnostics", None)

    rss_bytes = _current_rss_bytes(statm_path)
    return {
        "available": True,
        "mode": "PAPER_ONLY",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "process": {
            "resident_memory_bytes": rss_bytes,
            "resident_memory_source": "PROC_SELF_STATM" if rss_bytes is not None else "UNAVAILABLE",
            "active_thread_count": threading.active_count(),
            "gc_generation_counts": list(gc.get_count()),
        },
        "repository": {
            "position_count": sum(status_counts.values()),
            "status_counts": status_counts,
        },
        "paper_execution": {
            "stored_order_results": _safe_len(orders),
        },
        "runtime": {
            "entry_diagnostic_symbols": _safe_len(diagnostics),
        },
    }
