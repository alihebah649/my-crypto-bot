from engine.stop_structure import calculate_structural_stop_candidate

def test_scalp_uses_latest_closed_5m_pivot_low_below_entry():
    candles=[{"low":9.8,"high":10.2},{"low":9.5,"high":10.0},{"low":9.7,"high":10.1},{"low":9.2,"high":9.9},{"low":9.4,"high":10.0},{"low":9.1,"high":9.8},{"low":9.3,"high":9.9}]
    result=calculate_structural_stop_candidate(trade_mode="SCALP",entry_price=10.0,candles_by_timeframe={"5m":candles,"15m":[]})
    assert result.price==9.2
    assert result.source=="5m_PIVOT_LOW"

def test_swing_falls_back_to_1h():
    candles=[{"low":96.0,"high":102.0},{"low":92.0,"high":101.0},{"low":94.0,"high":103.0},{"low":97.0,"high":104.0}]
    result=calculate_structural_stop_candidate(trade_mode="SWING",entry_price=100.0,candles_by_timeframe={"15m":[],"1h":candles,"4h":[]})
    assert result.price==92.0
    assert result.source=="1h_PIVOT_LOW"

def test_no_closed_pivot_returns_none():
    result=calculate_structural_stop_candidate(trade_mode="SCALP",entry_price=10.0,candles_by_timeframe={"5m":[{"low":9.5,"high":10.1}],"15m":[]})
    assert result.price is None
    assert result.source is None
