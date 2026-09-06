"""Regression tests for the Paper-only risk overlay."""
from __future__ import annotations

from types import SimpleNamespace

from core.paper_risk_overlay import (
    BTC_RECOVERY_MAX_DRAWDOWN_PERCENT,
    REENTRY_COOLDOWN_SECONDS,
    btc_recovery_eligible,
    btc_recovery_stop,
    loss_cooldown_remaining,
    profit_protection_trigger,
    strong_bullish_btc_exception,
)


def test_loss_cooldown_blocks_recent_losing_symbol():
    closed = [SimpleNamespace(symbol="BTCUSDT", realized_pnl=-0.34, closed_at=1000.0)]
    remaining = loss_cooldown_remaining(closed, "BTCUSDT", now=1001.0)
    assert remaining == REENTRY_COOLDOWN_SECONDS - 1.0


def test_loss_cooldown_does_not_block_profitable_exit():
    closed = [SimpleNamespace(symbol="BTCUSDT", realized_pnl=0.50, closed_at=1000.0)]
    assert loss_cooldown_remaining(closed, "BTCUSDT", now=1001.0) == 0.0


def test_profit_protection_requires_profit_then_retrace():
    assert profit_protection_trigger(
        entry_price=100.0,
        current_price=100.60,
        highest_price=100.90,
        max_profit_percent=0.90,
    ) is True
    assert profit_protection_trigger(
        entry_price=100.0,
        current_price=99.80,
        highest_price=100.90,
        max_profit_percent=0.90,
    ) is False


def test_btc_recovery_requires_strong_setup_and_stays_bounded():
    score = {
        "swing_signal": "BUY",
        "swing_score": 88,
        "rsi5m": 40.0,
        "swing_reasons": ["EMA100_TREND"],
        "mtf_aligned_bullish": True,
    }
    assert btc_recovery_eligible(score, btc_crashing=False, pnl_percent=-0.8)
    assert not btc_recovery_eligible(score, btc_crashing=True, pnl_percent=-0.8)
    assert not btc_recovery_eligible(score, btc_crashing=False, pnl_percent=-1.21)
    assert btc_recovery_stop(100.0) == 100.0 * (1.0 - BTC_RECOVERY_MAX_DRAWDOWN_PERCENT / 100.0)


def test_btc_crash_exception_is_narrow():
    strong = {
        "swing_signal": "BUY",
        "swing_score": 92,
        "swing_reasons": ["EMA100_TREND", "5M_BULLISH_BREAKOUT_CONFIRMED"],
        "pattern_confirmed": True,
        "mtf_aligned_bullish": True,
    }
    weak_score = dict(strong, swing_score=89)
    no_mtf = dict(strong, mtf_aligned_bullish=False)
    assert strong_bullish_btc_exception(strong)
    assert not strong_bullish_btc_exception(weak_score)
    assert not strong_bullish_btc_exception(no_mtf)
