"""Paper engine liveness diagnostics used by the Render health check.

This module is intentionally decision-free: it only reports whether the
background Paper engine has a live thread and a recent heartbeat.
"""
from __future__ import annotations

import time
from threading import Thread
from typing import Mapping, Any


DEFAULT_MAX_AGE_SECONDS = 120.0


def snapshot(
    thread: Thread | None,
    heartbeat: Mapping[str, Any] | None,
    *,
    now: float | None = None,
    max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS,
) -> dict[str, Any]:
    observed_at = float(time.time() if now is None else now)
    heartbeat = heartbeat if isinstance(heartbeat, Mapping) else {}
    thread_alive = bool(thread is not None and thread.is_alive())

    heartbeat_at = None
    for candidate in (
        heartbeat.get("started_at"),
        heartbeat.get("finished_at"),
        heartbeat.get("thread_watchdog_at"),
    ):
        if candidate is not None:
            heartbeat_at = candidate
            break

    try:
        heartbeat_age = (
            None
            if heartbeat_at is None
            else max(0.0, observed_at - float(heartbeat_at))
        )
    except (TypeError, ValueError):
        heartbeat_age = None

    healthy = (
        thread_alive
        and heartbeat_age is not None
        and heartbeat_age <= float(max_age_seconds)
    )
    return {
        "status": "ok" if healthy else "unhealthy",
        "paper_only": True,
        "engine_thread_alive": thread_alive,
        "heartbeat_state": heartbeat.get("state"),
        "heartbeat_age_seconds": (
            None if heartbeat_age is None else round(heartbeat_age, 1)
        ),
        "max_heartbeat_age_seconds": float(max_age_seconds),
        "thread_last_exit": heartbeat.get("thread_last_exit"),
        "thread_exception": heartbeat.get("thread_exception"),
    }
