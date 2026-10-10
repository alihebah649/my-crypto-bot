from engine.entry_v2_adapter import _recovery_follow_through_shadow


def test_two_closed_bullish_candles_with_breakout_pass_shadow_experiment():
    candles = [
        {"open": 100.0, "high": 102.0, "low": 99.0, "close": 101.0},
        {"open": 101.0, "high": 104.0, "low": 100.5, "close": 103.0},
        # Current candle is forming and must not be used for the signal.
        {"open": 103.0, "high": 104.0, "low": 102.0, "close": 103.5},
    ]
    result = _recovery_follow_through_shadow(
        candles,
        trade_mode="SCALP",
        recovery_candidate=True,
        bearish_context=True,
    )

    assert result["shadow_only"] is True
    assert result["applicable"] is True
    assert result["available"] is True
    assert result["follow_through_confirmed"] is True
    assert result["would_be_action"] == "WOULD_ALLOW"


def test_single_bullish_recovery_bar_without_breakout_would_be_blocked_in_shadow():
    candles = [
        {"open": 100.0, "high": 102.0, "low": 99.0, "close": 101.0},
        {"open": 100.8, "high": 102.1, "low": 100.1, "close": 101.5},
        {"open": 101.5, "high": 103.0, "low": 101.1, "close": 102.5},
    ]
    result = _recovery_follow_through_shadow(
        candles,
        trade_mode="SCALP",
        recovery_candidate=True,
        bearish_context=True,
    )

    assert result["available"] is True
    assert result["second_closed_candle_bullish"] is True
    assert result["second_close_above_first_high"] is False
    assert result["follow_through_confirmed"] is False
    assert result["would_be_action"] == "WOULD_BLOCK"


def test_recovery_follow_through_is_not_applicable_outside_bearish_scalp_recovery():
    candles = [
        {"open": 100.0, "high": 102.0, "low": 99.0, "close": 101.0},
        {"open": 101.0, "high": 104.0, "low": 100.5, "close": 103.0},
        {"open": 103.0, "high": 104.0, "low": 102.0, "close": 103.5},
    ]
    result = _recovery_follow_through_shadow(
        candles,
        trade_mode="SCALP",
        recovery_candidate=True,
        bearish_context=False,
    )

    assert result["applicable"] is False
    assert result["follow_through_confirmed"] is True
    assert result["would_be_action"] == "NOT_APPLICABLE"


def test_recovery_follow_through_reports_insufficient_data_instead_of_allowing():
    result = _recovery_follow_through_shadow(
        [{"open": 100.0, "high": 102.0, "low": 99.0, "close": 101.0}],
        trade_mode="SCALP",
        recovery_candidate=True,
        bearish_context=True,
    )

    assert result["available"] is False
    assert result["follow_through_confirmed"] is None
    assert result["would_be_action"] == "INSUFFICIENT_DATA"


def test_non_bearish_context_is_not_applicable_even_when_two_closed_candles_are_unavailable():
    # Only one candle is closed; the last candle is still forming.
    candles = [
        {"open": 100.0, "high": 102.0, "low": 99.0, "close": 101.0},
        {"open": 101.0, "high": 104.0, "low": 100.5, "close": 103.0},
    ]
    result = _recovery_follow_through_shadow(
        candles,
        trade_mode="SCALP",
        recovery_candidate=True,
        bearish_context=False,
    )

    assert result["applicable"] is False
    assert result["available"] is False
    assert result["would_be_action"] == "NOT_APPLICABLE"
