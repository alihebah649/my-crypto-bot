"""Compact daily Paper-outcome diagnostics for Telegram reports.

This is presentation-only. It consumes aggregate metrics and never influences
strategy, risk, position management, or execution.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def _money(value: Any) -> str:
    if value is None or isinstance(value, bool):
        return "—"
    try:
        amount = float(value)
    except (TypeError, ValueError, OverflowError):
        return "—"
    return f"{amount:+.2f}$"


def _percent(value: Any) -> str:
    if value is None or isinstance(value, bool):
        return "—"
    try:
        return f"{float(value):.1f}%"
    except (TypeError, ValueError, OverflowError):
        return "—"


def _label(value: Any) -> str:
    label = str(value or "UNKNOWN").strip().upper() or "UNKNOWN"
    labels = {
        "AT_THRESHOLD_TO_PLUS4": "العتبة إلى +4",
        "THRESHOLD_PLUS5_TO_PLUS9": "+5 إلى +9 فوق العتبة",
        "THRESHOLD_PLUS10_OR_MORE": "+10 فأعلى فوق العتبة",
        "BELOW_THRESHOLD": "أقل من العتبة",
        "BELOW_65": "أقل من 65",
        "65_TO_79": "65–79",
        "80_TO_84": "80–84",
        "85_PLUS": "85 فأعلى",
        "UNKNOWN": "غير معروف",
        "TRAILING_STOP": "TRAILING_STOP",
        "STOP_LOSS": "STOP_LOSS",
        "TAKE_PROFIT": "TAKE_PROFIT",
    }
    return labels.get(label, label[:48])


def _group_lines(groups: Any, *, limit: int = 3, score_bands: bool = False) -> list[str]:
    if not isinstance(groups, Mapping):
        return []
    lines: list[str] = []
    for key, raw_stats in list(groups.items())[:limit]:
        if not isinstance(raw_stats, Mapping) or not raw_stats.get("records"):
            continue
        stats = raw_stats
        label = _label(key) if score_bands else str(key or "UNKNOWN")[:48]
        wins = int(stats.get("wins") or 0)
        losses = int(stats.get("losses") or 0)
        net = _money(stats.get("net_pnl"))
        lines.append(f"• {label}: {wins} ربح / {losses} خسارة | {net}")
    return lines


def format_paper_outcome_report(analysis: Mapping[str, Any]) -> str:
    """Format aggregate closed-trade diagnostics without any trade identifiers."""
    totals = analysis.get("totals", {})
    if not isinstance(totals, Mapping):
        totals = {}
    quality = analysis.get("data_quality", {})
    if not isinstance(quality, Mapping):
        quality = {}

    wins = int(totals.get("wins") or 0)
    losses = int(totals.get("losses") or 0)
    flats = int(totals.get("flat") or 0)
    record_count = int(totals.get("records", analysis.get("record_count", 0)) or 0)
    win_rate = _percent(totals.get("win_rate_percent"))
    profit_factor = totals.get("profit_factor")
    profit_factor_text = "—"
    if profit_factor is not None:
        try:
            profit_factor_text = f"{float(profit_factor):.2f}"
        except (TypeError, ValueError, OverflowError):
            pass

    lines = [
        "🔬 تحليل الصفقات المغلقة — PAPER",
        f"📦 الصفقات: {record_count} | ربح: {wins} | خسارة: {losses} | تعادل: {flats}",
        f"🎯 نسبة الفوز: {win_rate} | Profit Factor: {profit_factor_text}",
        f"💵 صافي بعد الرسوم: {_money(totals.get('net_pnl'))}",
        (
            f"📈 متوسط الربح: {_money(totals.get('avg_win_net_pnl'))}"
            f" | 📉 متوسط الخسارة: {_money(totals.get('avg_loss_net_pnl'))}"
        ),
        f"💳 مجموع الرسوم: {_money(totals.get('fees'))}",
    ]

    by_mode = _group_lines(analysis.get("by_trade_mode"), limit=4)
    if by_mode:
        lines.extend(["", "🎯 حسب النمط:", *by_mode])

    by_source = _group_lines(analysis.get("by_market_data_source"), limit=4)
    if by_source:
        lines.extend(["", "📡 حسب مصدر البيانات:", *by_source])

    by_close = _group_lines(analysis.get("by_close_reason"), limit=3)
    if by_close:
        lines.extend(["", "🚪 حسب سبب الإغلاق (الأكثر تكرارًا):", *by_close])

    by_score = _group_lines(analysis.get("by_entry_score_band"), limit=4, score_bands=True)
    if by_score:
        lines.extend(["", "📊 حسب نطاق درجة الدخول:", *by_score])

    missing_pnl = int(totals.get("records_missing_net_pnl") or 0)
    if missing_pnl:
        lines.append(f"⚠ سجلات ينقصها صافي الربح/الخسارة: {missing_pnl}")
    missing_context = int(quality.get("records_missing_entry_context") or 0)
    if missing_context:
        lines.append(f"⚠ سجلات ينقصها سياق الدخول: {missing_context}")

    return "\n".join(lines)


__all__ = ["format_paper_outcome_report"]
