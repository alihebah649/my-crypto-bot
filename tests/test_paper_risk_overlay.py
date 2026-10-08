"""Regression tests for the Paper-only risk overlay."""
from __future__ import annotations

from types import SimpleNamespace

from core.paper_risk_overlay import (
    BTC_RECOVERY_MAX_DRAWDOWN_PERCENT,
    REENTRY_COOLDOWN_SECONDS,
    btc_recovery_eligible,
    btc_recovery_stop,
    loss_cooldown_remaining,
    paper_stop_fill_price,
    profit_protection_snapshot,
    profit_protection_trigger,
    strong_bullish_btc_exception,
    paper_entry_economics,
)


def test_loss_cooldown_blocks_recent_losing_symbol():
    closed = [SimpleNamespace(symbol="BTCUSDT", realized_pnl=-0.34, closed_at=1000.0)]
    remaining = loss_cooldown_remaining(closed, "BTCUSDT", now=1001.0)
    assert remaining == REENTRY_COOLDOWN_SECONDS - 1.0


def test_loss_cooldown_does_not_block_profitable_exit():
    closed = [SimpleNamespace(symbol="BTCUSDT", realized_pnl=0.50, closed_at=1000.0)]
    assert loss_cooldown_remaining(closed, "BTCUSDT", now=1001.0) == 0.0


def test_profit_protection_uses_calibrated_floor_and_retrace():
    assert profit_protection_trigger(
        entry_price=100.0,
        current_price=100.80,
        highest_price=101.30,
        max_profit_percent=1.30,
    ) is True
    assert profit_protection_trigger(
        entry_price=100.0,
        current_price=100.50,
        highest_price=101.30,
        max_profit_percent=1.30,
    ) is False
    snapshot = profit_protection_snapshot(
        entry_price=100.0,
        current_price=100.80,
        highest_price=101.30,
        max_profit_percent=1.30,
    )
    assert snapshot["triggered"] is True
    assert snapshot["current_gain_percent"] == 0.8
    assert snapshot["retrace_percent"] > 0.35


def test_paper_stop_fill_uses_configured_stop_after_polling_breach():
    assert paper_stop_fill_price(99.0, 98.2) == 99.0
    assert paper_stop_fill_price(99.0, 99.2) == 99.2


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


def test_paper_entry_economics_rejects_missing_target():
    result = paper_entry_economics(
        trade_mode="SCALP",
        entry_price=100.0,
        stop_loss=99.4,
        target_price=None,
        target_status="NO_TARGET_MEETS_RR",
        reward_risk=None,
        fee_rate=0.001,
    )
    assert result["approved"] is False
    assert result["reason"] == "NO_VALID_TARGET"


def test_paper_entry_economics_rejects_low_rr():
    result = paper_entry_economics(
        trade_mode="SCALP",
        entry_price=100.0,
        stop_loss=99.4,
        target_price=100.6849,
        target_status="VALID",
        reward_risk=1.1415,
        fee_rate=0.001,
    )
    assert result["approved"] is False
    assert result["reason"] == "REWARD_RISK_TOO_LOW"


def test_paper_entry_economics_preserves_near_like_winner():
    result = paper_entry_economics(
        trade_mode="SCALP",
        entry_price=5.0,
        stop_loss=4.8807,
        target_price=5.1486,
        target_status="VALID",
        reward_risk=1.2445,
        fee_rate=0.001,
    )
    assert result["approved"] is True
    assert result["net_reward_percent"] > 0.20


def test_paper_entry_economics_rejects_fee_thin_target():
    result = paper_entry_economics(
        trade_mode="SCALP",
        entry_price=100.0,
        stop_loss=99.9,
        target_price=100.39,
        target_status="VALID",
        reward_risk=3.9,
        fee_rate=0.001,
    )
    assert result["approved"] is False
    assert result["reason"] == "NET_REWARD_AFTER_FEES_TOO_LOW"
