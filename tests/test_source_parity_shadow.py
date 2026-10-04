from core.source_parity_shadow import build_source_parity_shadow


def _candles(count: int, *, start: float = 100.0) -> list[dict]:
    rows = []
    for index in range(count):
        close = start + index * 0.1
        rows.append({
            "open_time": index + 1,
            "close_time": index + 1,
            "open": close - 0.2,
            "high": close + 0.3,
            "low": close - 0.3,
            "close": close,
            "volume": 10.0,
        })
    return rows


def test_source_parity_shadow_reports_zero_delta_for_identical_inputs():
    candles_15m = _candles(110)
    candles_5m = _candles(60)

    result = build_source_parity_shadow(
        source_ticker={"lastPrice": 110.9},
        source_15m_candles=candles_15m,
        source_5m_candles=candles_5m,
        binance_ticker={"lastPrice": 110.9},
        binance_15m_candles=candles_15m,
        binance_5m_candles=candles_5m,
    )

    assert result["status"] == "READY"
    assert result["diagnostic_only"] is True
    assert result["categorical_comparison"]["pattern_match"] is True
    assert result["numeric_delta_source_minus_binance"]["rsi5m"] == 0.0
    assert result["numeric_delta_source_minus_binance"]["volume_ratio_5m"] == 0.0


def test_source_parity_shadow_exposes_source_specific_feature_deltas():
    source_15m = _candles(110)
    reference_15m = _candles(110)
    source_5m = _candles(60)
    reference_5m = _candles(60)

    source_ticker = {"lastPrice": 120.0}
    reference_ticker = {"lastPrice": 110.0}
    source_5m[-2]["volume"] = 20.0
    source_5m[-1]["volume"] = 30.0

    result = build_source_parity_shadow(
        source_ticker=source_ticker,
        source_15m_candles=source_15m,
        source_5m_candles=source_5m,
        binance_ticker=reference_ticker,
        binance_15m_candles=reference_15m,
        binance_5m_candles=reference_5m,
    )

    assert result["status"] == "READY"
    assert result["numeric_delta_source_minus_binance"]["price"] == 10.0
    assert result["numeric_delta_source_minus_binance"]["volume_ratio_5m"] > 0.0
