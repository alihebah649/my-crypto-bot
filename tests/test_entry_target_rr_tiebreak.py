from engine.entry_target_rr import calculate_target_rr


def c(high: float):
    return {"open": high - 0.2, "high": high, "low": high - 0.5, "close": high - 0.1, "volume": 100.0}


def test_scalp_prefers_5m_when_price_target_is_identical():
    candles_5m = [c(99), c(102), c(100), c(101)]
    candles_15m = [c(99), c(102), c(100), c(101)]
    result = calculate_target_rr(
        trade_mode="SCALP",
        entry_price=100.0,
        stop_loss=98.0,
        candles_by_timeframe={"5m": candles_5m, "15m": candles_15m, "1h": [], "4h": []},
    )
    assert result.target_price == 102.0
    assert result.target_source == "5m_PIVOT_HIGH"
