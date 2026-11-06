"""Venue-specific daily Telegram reports for hosted Paper labs.

This module is presentation-only. It formats already-persisted closed outcomes
and cannot influence strategy, risk, Trade Manager, or Paper execution.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Any

from core.paper_outcome_analysis import build_paper_outcome_analysis
from core.paper_outcome_report import format_paper_outcome_report


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if result == result and result not in (float("inf"), float("-inf")) else None


def format_hosted_lab_daily_report(
    venue: str,
    date_key: str,
    records: Iterable[Mapping[str, Any]],
) -> str:
    """Format a single venue's closed outcomes; records must already be date-scoped."""
    venue_name = str(venue or "").strip().upper()
    if venue_name not in {"BYBIT", "OKX"}:
        raise ValueError(f"unsupported hosted Paper lab venue: {venue_name or 'EMPTY'}")

    rows = [dict(record) for record in records if isinstance(record, Mapping)]
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for record in rows:
        symbol = str(record.get("symbol") or "").strip().upper()
        if symbol:
            grouped[symbol.removesuffix("USDT")].append(record)

    lines = [
        f"🤖 BOT: {venue_name} PAPER LAB",
        f"🏷️ VENUE: {venue_name} SPOT ONLY",
        "📊 حصاد اليوم الشامل (PAPER TRADING)",
        f"📅 التاريخ المنتهي: {date_key}",
        "",
        "```",
        f"{'COIN':<8} | {'WIN':<3} | {'LOSS':<4} | {'NET (FEES)':<10}",
        "---------------------------------",
    ]

    total_wins = 0
    total_losses = 0
    total_net = 0.0
    rows_with_pnl = 0
    for coin in sorted(grouped):
        wins = losses = 0
        net = 0.0
        for record in grouped[coin]:
            pnl = _number(record.get("realized_pnl"))
            if pnl is None:
                continue
            rows_with_pnl += 1
            net += pnl
            if pnl > 0:
                wins += 1
            elif pnl < 0:
                losses += 1
        total_wins += wins
        total_losses += losses
        total_net += net
        lines.append(f"{coin:<8} | {wins:<3} | {losses:<4} | {net:+.2f}$")

    if not grouped:
        lines.append("لا توجد صفقات مغلقة في هذا اليوم")
    lines.extend([
        "---------------------------------",
        f"{'TOTAL':<8} | {total_wins:<3} | {total_losses:<4} | {total_net:+.2f}$"
        if rows_with_pnl else f"{'TOTAL':<8} | {'0':<3} | {'0':<4} | {'—':<10}",
        "```",
        "📚 مصدر النتائج: Postgres PAPER_OUTCOME",
        "",
        format_paper_outcome_report(build_paper_outcome_analysis(rows)),
        "PAPER ONLY",
    ])
    return "\n".join(lines)


__all__ = ["format_hosted_lab_daily_report"]
