from core.entry_freshness_audit import audit_5m_entry_freshness


def _candles(*close_times):
    return [
        {
            "open_time": int(close - 299_000),
            "close_time": int(close),
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "volume": 10.0,
        }
        for close in close_times
    ]


def test_open_latest_candle_uses_previous_closed_candle_and_reports_age():
    captured = 1_720_000_300.0
    candles = _candles(
        int((captured - 60.0) * 1000),
        int((captured + 100.0) * 1000),
    )
    result = audit_5m_entry_freshness(
        candles_5m=candles,
        captured_at=captured,
        cache_timestamp=captured - 20.0,
        cache_ttl_seconds=310.0,
    )

    assert result["latest_raw_candle_open"] is True
    assert result["decision_candle_close_time_ms"] == candles[-2]["close_time"]
    assert result["cache_age_seconds"] == 20.0
    assert result["state"] == "FRESH"


def test_expired_snapshot_is_marked_stale_even_when_candle_is_recent():
    captured = 1_720_000_600.0
    candles = _candles(
        int((captured - 30.0) * 1000),
        int((captured - 5.0) * 1000),
    )
    result = audit_5m_entry_freshness(
        candles_5m=candles,
        captured_at=captured,
        cache_timestamp=captured - 311.0,
        cache_ttl_seconds=310.0,
    )

    assert result["latest_raw_candle_open"] is False
    assert result["cache_expired"] is True
    assert result["state"] == "STALE"


def test_closed_latest_candle_is_the_decision_candle():
    captured = 1_720_000_300.0
    candles = _candles(
        int((captured - 300.0) * 1000),
        int((captured - 30.0) * 1000),
    )
    result = audit_5m_entry_freshness(
        candles_5m=candles,
        captured_at=captured,
        cache_timestamp=captured - 20.0,
        cache_ttl_seconds=310.0,
    )

    assert result["latest_raw_candle_open"] is False
    assert result["decision_candle_close_time_ms"] == candles[-1]["close_time"]
    assert result["decision_candle_age_seconds"] == 30.0
    assert result["state"] == "FRESH"
