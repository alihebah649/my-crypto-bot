"""Venue-scoped policy for periodic Paper market-health Telegram notifications."""
from __future__ import annotations


def should_notify_market_health(
    *,
    venue_mode: str,
    changed: bool,
    heartbeat_due: bool,
    force: bool = False,
) -> bool:
    """Always report state transitions; only MIXED/main gets hourly heartbeats."""
    if force or changed:
        return True
    return str(venue_mode or "UNKNOWN").strip().upper() == "MIXED" and heartbeat_due


__all__ = ["should_notify_market_health"]
