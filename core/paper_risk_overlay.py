"""Paper-only risk overlay for the Shadow Trading entrypoint.

This module sits outside Trade Manager. It addresses observed Paper Trading
failure modes at the orchestration boundary without changing strategy scores
or the Trade Manager implementation.
"""
from __future__ import annotations

import os
from typing import Any, Iterable

REENTRY_COOLDOWN_SECONDS = 2.0 * 60.0 * 60.0
PROFIT_PROTECTION_MIN_GAIN_PERCENT = float(os.getenv("PAPER_PROFIT_PROTECTION_MIN_GAIN_PERCENT", "0.60"))
PROFIT_PROTECTION_MIN_RETRACE_PERCENT = float(os.getenv("PAPER_PROFIT_PROTECTION_MIN_RETRACE_PERCENT", "0.35"))
BTC_RECOVERY_MAX_DRAWDOWN_PERCENT = 1.20

PAPER_SCALP_MIN_REWARD_RISK = float(os.getenv("PAPER_SCALP_MIN_REWARD_RISK", "1.20"))
PAPER_SWING_MIN_REWARD_RISK = float(os.getenv("PAPER_SWING_MIN_REWARD_RISK", "1.50"))
PAPER_MIN_NET_REWARD_PERCENT = float(os.getenv("PAPER_MIN_NET_REWARD_PERCENT", "0.20"))
PAPER_DEFAULT_FEE_RATE = float(os.getenv("PAPER_DEFAULT_FEE_RATE", "0.001"))


def paper_entry_economics(
    *,
    trade_mode: str,
    entry_price: float,
    stop_loss: float,
    target_price: float | None,
    target_status: str | None,
    reward_risk: float | None,
    fee_rate: float = PAPER_DEFAULT_FEE_RATE,
) -> dict[str, Any]:
    """Selective Paper-only entry economics check using current target evidence."""
    mode = str(trade_mode or "").upper()
    required_rr = (
        PAPER_SCALP_MIN_REWARD_RISK
        if mode == "SCALP"
        else PAPER_SWING_MIN_REWARD_RISK
        if mode == "SWING"
        else max(PAPER_SCALP_MIN_REWARD_RISK, PAPER_SWING_MIN_REWARD_RISK)
    )
    entry = float(entry_price or 0.0)
    stop = float(stop_loss or 0.0)
    target = float(target_price or 0.0)
    fee = max(0.0, float(fee_rate or 0.0))
    round_trip_fee_percent = fee * 2.0 * 100.0

    result = {
        "available": bool(target_status is not None or reward_risk is not None or target > 0.0),
        "trade_mode": mode,
        "entry_price": entry,
        "stop_loss": stop,
        "target_price": target if target > 0.0 else None,
        "target_status": str(target_status or ""),
        "reward_risk": float(reward_risk) if reward_risk is not None else None,
        "required_reward_risk": required_rr,
        "round_trip_fee_percent": round_trip_fee_percent,
        "minimum_net_reward_percent": PAPER_MIN_NET_REWARD_PERCENT,
    }

    # Entry v2 remains advisory: if no target evidence is available, record a
    # bypass rather than inventing a target or vetoing a Legacy entry.
    if not result["available"]:
        result.update({
            "approved": True,
            "reason": "TARGET_DATA_UNAVAILABLE",
            "net_reward_percent": None,
        })
        return result

    if entry <= 0.0 or stop <= 0.0 or stop >= entry:
        result.update({
            "approved": False,
            "reason": "INVALID_STOP_DISTANCE",
            "net_reward_percent": None,
        })
        return result

    risk_percent = (entry - stop) / entry * 100.0
    if target <= entry or str(target_status or "").upper() != "VALID":
        result.update({
            "approved": False,
            "reason": "NO_VALID_TARGET",
            "risk_percent": risk_percent,
            "gross_reward_percent": max(0.0, (target - entry) / entry * 100.0) if target > 0.0 else 0.0,
            "net_reward_percent": None,
        })
        return result

    gross_reward_percent = (target - entry) / entry * 100.0
    computed_rr = (target - entry) / (entry - stop)
    rr = computed_rr if reward_risk is None else float(reward_risk)
    net_reward_percent = gross_reward_percent - round_trip_fee_percent
    result.update({
        "risk_percent": risk_percent,
        "gross_reward_percent": gross_reward_percent,
        "net_reward_percent": net_reward_percent,
        "computed_reward_risk": computed_rr,
        "reward_risk": rr,
    })

    if rr < required_rr:
        result.update({"approved": False, "reason": "REWARD_RISK_TOO_LOW"})
        return result
    if net_reward_percent < PAPER_MIN_NET_REWARD_PERCENT:
        result.update({"approved": False, "reason": "NET_REWARD_AFTER_FEES_TOO_LOW"})
        return result

    result.update({"approved": True, "reason": "APPROVED"})
    return result



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


def profit_protection_snapshot(
    *,
    entry_price: float,
    current_price: float,
    highest_price: float,
    max_profit_percent: float,
    min_gain_percent: float = PROFIT_PROTECTION_MIN_GAIN_PERCENT,
    min_retrace_percent: float = PROFIT_PROTECTION_MIN_RETRACE_PERCENT,
) -> dict[str, float | bool]:
    if entry_price <= 0 or current_price <= 0 or highest_price <= 0:
        return {
            "triggered": False,
            "current_gain_percent": 0.0,
            "peak_gain_percent": float(max_profit_percent),
            "retrace_percent": 0.0,
            "min_gain_percent": float(min_gain_percent),
            "min_retrace_percent": float(min_retrace_percent),
        }
    current_gain = (current_price - entry_price) / entry_price * 100.0
    retrace = (highest_price - current_price) / highest_price * 100.0
    triggered = bool(
        max_profit_percent >= min_gain_percent
        and current_gain >= min_gain_percent
        and retrace >= min_retrace_percent
        and current_price < highest_price
    )
    return {
        "triggered": triggered,
        "current_gain_percent": round(current_gain, 6),
        "peak_gain_percent": round(float(max_profit_percent), 6),
        "retrace_percent": round(retrace, 6),
        "min_gain_percent": float(min_gain_percent),
        "min_retrace_percent": float(min_retrace_percent),
    }


def profit_protection_trigger(
    *,
    entry_price: float,
    current_price: float,
    highest_price: float,
    max_profit_percent: float,
    min_gain_percent: float = PROFIT_PROTECTION_MIN_GAIN_PERCENT,
    min_retrace_percent: float = PROFIT_PROTECTION_MIN_RETRACE_PERCENT,
) -> bool:
    return bool(
        profit_protection_snapshot(
            entry_price=entry_price,
            current_price=current_price,
            highest_price=highest_price,
            max_profit_percent=max_profit_percent,
            min_gain_percent=min_gain_percent,
            min_retrace_percent=min_retrace_percent,
        )["triggered"]
    )


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
