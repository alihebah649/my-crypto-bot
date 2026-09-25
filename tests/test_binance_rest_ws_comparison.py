import pytest

from core.binance_rest_ws_comparison import compare_rest_ws_candle, normalize_rest_candles


def test_compare_rest_ws_closed_candle_match():
    rest = [
        {
            "open_time": 1000,
            "open": 10.0,
            "high": 11.0,
            "low": 9.5,
            "close": 10.5,
            "volume": 25.0,
        }
    ]
    ws = {
        "open_time": 1000,
        "open": 10.0,
        "high": 11.0,
        "low": 9.5,
        "close": 10.5,
        "volume": 25.0,
        "is_closed": True,
    }

    result = compare_rest_ws_candle(rest, ws)

    assert result["status"] == "MATCH"
    assert result["fields_match"] is True
    assert result["max_abs_diff"] == 0.0


def test_compare_rest_ws_detects_divergence_on_same_candle():
    rest = [
        {
            "open_time": 1000,
            "open": 10.0,
            "high": 11.0,
            "low": 9.5,
            "close": 10.5,
            "volume": 25.0,
        }
    ]
    ws = {
        "open_time": 1000,
        "open": 10.0,
        "high": 11.0,
        "low": 9.5,
        "close": 10.51,
        "volume": 25.0,
        "is_closed": True,
    }

    result = compare_rest_ws_candle(rest, ws)

    assert result["status"] == "DIVERGENCE"
    assert result["fields_match"] is False
    assert result["max_abs_diff"] == pytest.approx(0.01)


def test_compare_rest_ws_ignores_unclosed_websocket_candle():
    result = compare_rest_ws_candle(
        [{"open_time": 1000, "open": 10, "high": 11, "low": 9, "close": 10, "volume": 1}],
        {"open_time": 1000, "open": 10, "high": 11, "low": 9, "close": 10, "volume": 1, "is_closed": False},
    )

    assert result["status"] == "NO_WS_CLOSED_CANDLE"


def test_normalize_rest_candles_filters_invalid_rows():
    payload = [
        {
            "open_time": "1000",
            "open": "10",
            "high": "11",
            "low": "9",
            "close": "10.5",
            "volume": "25",
            "close_time": "1299",
        },
        {"open_time": "bad"},
    ]

    result = normalize_rest_candles(payload)

    assert result == [{
        "open_time": 1000,
        "open": 10.0,
        "high": 11.0,
        "low": 9.0,
        "close": 10.5,
        "volume": 25.0,
        "close_time": 1299,
    }]
