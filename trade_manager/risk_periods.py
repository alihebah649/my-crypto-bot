"""Deterministic reporting periods for Paper Trading risk controls."""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

REPORT_TIMEZONE = ZoneInfo("Asia/Aden")


def period_keys(when: datetime) -> tuple[str, str, str]:
    """Return daily, ISO-week and monthly keys in the bot reporting timezone."""
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    local = when.astimezone(REPORT_TIMEZONE)
    return local.strftime("%Y-%m-%d"), local.strftime("%G-W%V"), local.strftime("%Y-%m")


def same_period(a: datetime, b: datetime) -> bool:
    """Return True when two timestamps belong to the same reporting periods."""
    return period_keys(a) == period_keys(b)
