"""Paper-only risk overlay for the Shadow Trading entrypoint.

This module sits outside Trade Manager. It addresses observed Paper Trading
failure modes at the orchestration boundary without changing strategy scores
or the Trade Manager implementation.
"""
from __future__ import annotations

from typing import Any, Iterable

REENTRY_COOLDOWN_SECONDS = 2.0 * 60.0 * 60.0
PROFIT_PROTECTION_MIN_GAIN_PERCENT = 0.35
PROFIT_PROTECTION_MIN_RETRACE_PERCENT = 0.20
BTC_RECOVERY_MAX_DRAWDOWN_PERCENT = 1.20


def loss_cooldown_remaining(positions: Iterable[Any], symbol: str, *, now: float, cooldown_seconds: float = REENTRY_COOLDOWN_SECONDS) -> float:
    target = str(symbol).upper()
    latest_loss = 0.0
    for position in positions:
        if str(getattr(position, "symbol", "")).upper() != target:
            continue
        if float(getattr(position, "realized_pnl", 0.0) or 0.0) >= 0.0:
            continue
        closed_at = float(getattr(position, "closed_at", 0.0) or 0.0)
        latest_loss = max(latest_loss, closed_at)
    if latest_loss <= 0.0:
        return 0.0
    return max(0.0, latest_loss + cooldown_seconds - float(now))


def strong_bullish_btc_exception(score: dict[str, Any]) -> bool:
    swing_reasons = set(score.get("swing_reasons", []) or [])
    return bool(
        score.get("swing_signal") == "BUY"
        and float(score.get("swing_score", 0.0) or 0.0) >= 90.0
        and "EMA100_TREND" in swing_reasons
        and bool(score.get("pattern_confirmed"))
        and bool(score.get("mtf_aligned_bullish"))
    )


def profit_protection_trigger(*, entry_price: float, current_price: float, highest_price: float, max_profit_percent: float, min_gain_percent: float = PROFIT_PROTECTION_MIN_GAIN_PERCENT, min_retrace_percent: float = PROFIT_PROTECTION_MIN_RETRACE_PERCENT) -> bool:
    if entry_price <= 0 or current_price <= 0 or highest_price <= 0:
        return False
    current_gain = (current_price - entry_price) / entry_price * 100.0
    retrace = (highest_price - current_price) / highest_price * 100.0
    return bool(max_profit_percent >= min_gain_percent and current_gain >= min_gain_percent and retrace >= min_retrace_percent and current_price < highest_price)


def btc_recovery_eligible(score: dict[str, Any], *, btc_crashing: bool, pnl_percent: float, max_drawdown_percent: float = BTC_RECOVERY_MAX_DRAWDOWN_PERCENT) -> bool:
    if btc_crashing or pnl_percent >= 0.0 or abs(pnl_percent) > max_drawdown_percent:
        return False
    return bool(
        float(score.get("swing_score", 0.0) or 0.0) >= 80.0
        and score.get("swing_signal") == "BUY"
        and float(score.get("rsi5m", 100.0) or 100.0) <= 45.0
        and ("EMA100_TREND" in set(score.get("swing_reasons", []) or []) or bool(score.get("mtf_aligned_bullish")))
    )


def btc_recovery_stop(entry_price: float, *, max_drawdown_percent: float = BTC_RECOVERY_MAX_DRAWDOWN_PERCENT) -> float:
    return float(entry_price) * (1.0 - float(max_drawdown_percent) / 100.0)


def paper_stop_fill_price(stop_price: float, current_price: float) -> float:
    """Use the configured stop as the Paper fill when polling detects a breach."""
    if stop_price <= 0 or current_price <= 0:
        return float(current_price)
    return float(stop_price) if current_price < stop_price else float(current_price)
