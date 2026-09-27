from core.execution_market_alignment import assess_execution_market_alignment


def _candle(open_time, open_price, high, low, close, close_time):
    return {
        "open_time": open_time,
        "close_time": close_time,
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "volume": 100.0,
    }


def _aligned_inputs():
    now = 1_000_000.0
    five_open = 999_700_000
    five_close = 999_999_999
    fifteen_open = 999_100_000
    fifteen_close = 999_999_999
    return {
        "market_data_source": "BYBIT",
        "source_ticker": {"lastPrice": 100.00},
        "source_5m_candles": [_candle(five_open, 99.0, 101.0, 98.5, 100.0, five_close)],
        "source_15m_candles": [_candle(fifteen_open, 98.0, 101.0, 97.5, 100.0, fifteen_close)],
        "binance_ticker": {"lastPrice": 100.10, "received_at": 999_990.0},
        "binance_5m_closed": _candle(five_open, 99.1, 101.1, 98.6, 100.1, five_close),
        "binance_15m_closed": _candle(fifteen_open, 98.1, 101.1, 97.6, 100.1, fifteen_close),
        "binance_stream_healthy": True,
        "now": now,
    }


def test_bybit_signal_requires_binance_alignment():
    kwargs = _aligned_inputs()
    result = assess_execution_market_alignment(**kwargs)
    assert result["eligible"] is True
    assert result["reason"] == "BINANCE_SPOT_STATE_CONFIRMED"


def test_price_divergence_blocks_cross_venue_entry():
    kwargs = _aligned_inputs()
    kwargs["binance_ticker"] = {"lastPrice": 101.0, "received_at": 999_990.0}
    result = assess_execution_market_alignment(**kwargs)
    assert result["eligible"] is False
    assert result["reason"] == "PRICE_DIVERGENCE"


def test_5m_direction_mismatch_blocks_entry():
    kwargs = _aligned_inputs()
    kwargs["binance_5m"] = _candle(999_700_000, 101.0, 101.5, 99.0, 99.5, 999_999_999)
    result = assess_execution_market_alignment(**kwargs)
    assert result["eligible"] is False
    assert result["reason"] == "5M_CANDLE_DIRECTION_MISMATCH"


def test_15m_direction_mismatch_blocks_entry():
    kwargs = _aligned_inputs()
    kwargs["binance_15m"] = _candle(999_100_000, 101.0, 101.5, 99.0, 100.0 - 0.3, 999_999_999)
    result = assess_execution_market_alignment(**kwargs)
    assert result["eligible"] is False
    assert result["reason"] == "15M_CANDLE_DIRECTION_MISMATCH"


def test_unhealthy_binance_reference_blocks_bybit_entry():
    kwargs = _aligned_inputs()
    kwargs["binance_stream_healthy"] = False
    result = assess_execution_market_alignment(**kwargs)
    assert result["eligible"] is False
    assert result["reason"] == "BINANCE_REFERENCE_STREAM_UNHEALTHY"


def test_binance_signal_is_same_venue_and_does_not_need_cross_venue_gate():
    result = assess_execution_market_alignment(
        market_data_source="BINANCE",
        source_ticker={"lastPrice": 100.0},
        source_5m_candles=[],
        source_15m_candles=[],
        binance_ticker=None,
        binance_5m_closed=None,
        binance_15m_closed=None,
        binance_stream_healthy=False,
        now=1_000_000.0,
    )
    assert result["eligible"] is True
    assert result["status"] == "SAME_EXECUTION_VENUE"
