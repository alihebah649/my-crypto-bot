import pytest

from core.brain_shadow_outcome import record_shadow_outcome


def test_buy_outcome_is_positive_when_price_rises():
    result = record_shadow_outcome(
        {"symbol": "BTCUSDT"},
        action="BUY",
        horizon="15m",
        entry_price=100.0,
        outcome_price=102.0,
    )
    assert result.return_percent == pytest.approx(2.0)
    assert result.favorable is True


def test_exit_outcome_is_positive_when_price_falls():
    result = record_shadow_outcome(
        {"symbol": "ETHUSDT"},
        action="EXIT",
        horizon="1h",
        entry_price=100.0,
        outcome_price=97.0,
    )
    assert result.return_percent == pytest.approx(3.0)
    assert result.favorable is True


def test_invalid_entry_price_is_rejected():
    with pytest.raises(ValueError):
        record_shadow_outcome(
            {"symbol": "BTCUSDT"},
            action="BUY",
            horizon="5m",
            entry_price=0,
            outcome_price=100,
        )


def test_unknown_action_is_rejected():
    with pytest.raises(ValueError):
        record_shadow_outcome(
            {"symbol": "BTCUSDT"},
            action="MOON",
            horizon="5m",
            entry_price=100,
            outcome_price=101,
        )
