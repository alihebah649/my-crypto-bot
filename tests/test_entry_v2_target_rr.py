from engine.entry_target_rr import calculate_target_rr


def candle(o, c, low, high):
    return {"open": o, "close": c, "low": low, "high": high, "volume": 100.0}


def test_scalp_uses_nearest_5m_pivot_that_meets_rr():
    candles_5m = [
        candle(100, 101, 99, 100),
        candle(101, 100, 99, 102),
        candle(100, 101, 99, 101),
        candle(101, 100, 99, 105),
        candle(100, 101, 99, 104),
        candle(100, 100.5, 99.5, 100.8),
    ]
    result = calculate_target_rr(
        trade_mode="SCALP",
        entry_price=100.0,
        stop_loss=98.0,
        candles_by_timeframe={"5m": candles_5m, "15m": [], "1h": [], "4h": []},
    )
    assert result.status == "VALID"
    assert result.target_price == 102.0
    assert result.target_source == "5m_PIVOT_HIGH"
    assert result.reward_risk == 1.0


def test_closest_target_can_be_skipped_when_it_does_not_meet_rr():
    candles = [
        candle(100, 101, 99, 100),
        candle(101, 100, 99, 102),
        candle(100, 101, 99, 101),
        candle(101, 100, 99, 105),
        candle(100, 101, 99, 104),
        candle(100, 100.5, 99.5, 100.8),
    ]
    result = calculate_target_rr(
        trade_mode="SWING",
        entry_price=100.0,
        stop_loss=98.0,
        candles_by_timeframe={"5m": candles, "15m": candles, "1h": [], "4h": []},
    )
    assert result.status == "VALID"
    assert result.target_price == 105.0
    assert result.reward_risk == 2.5


def test_forming_last_candle_is_never_used_as_target():
    candles = [
        candle(100, 101, 99, 102),
        candle(101, 100, 99, 104),
        candle(100, 101, 99, 103),
        candle(101, 100, 99, 102),
        candle(100, 100.5, 99.5, 150),
    ]
    result = calculate_target_rr(
        trade_mode="SCALP",
        entry_price=100.0,
        stop_loss=98.0,
        candles_by_timeframe={"5m": candles, "15m": [], "1h": [], "4h": []},
    )
    assert result.target_price != 150.0


def test_swing_can_use_higher_timeframe_structure():
    candles_1h = [
        candle(100, 101, 99, 100),
        candle(101, 100, 99, 108),
        candle(100, 101, 99, 112),
        candle(101, 100, 99, 109),
        candle(100, 100.5, 99.5, 101),
    ]
    result = calculate_target_rr(
        trade_mode="SWING",
        entry_price=100.0,
        stop_loss=96.0,
        candles_by_timeframe={"5m": [], "15m": [], "1h": candles_1h, "4h": []},
    )
    assert result.status == "VALID"
    assert result.target_price == 112.0
    assert result.target_source == "1h_PIVOT_HIGH"
    assert result.reward_risk == 3.0


def test_no_target_meets_rr_is_not_reported_as_valid():
    candles = [
        candle(100, 101, 99, 102),
        candle(101, 100, 99, 103),
        candle(100, 101, 99, 102),
        candle(101, 100, 99, 103),
        candle(100, 100.5, 99.5, 100.8),
    ]
    result = calculate_target_rr(
        trade_mode="SWING",
        entry_price=100.0,
        stop_loss=90.0,
        candles_by_timeframe={"5m": [], "15m": candles, "1h": [], "4h": []},
    )
    assert result.status == "NO_TARGET_MEETS_RR"
    assert result.target_price is None
    assert result.reward_risk is not None


def test_invalid_stop_fails_closed():
    result = calculate_target_rr(
        trade_mode="SCALP",
        entry_price=100.0,
        stop_loss=101.0,
        candles_by_timeframe={"5m": [], "15m": [], "1h": [], "4h": []},
    )
    assert result.status == "INVALID_RISK_INPUT"
    assert result.target_price is None
    assert result.reward_risk is None
