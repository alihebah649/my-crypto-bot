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


def test_compare_rest_ws_snapshot_predates_candle_close():
    rest = [{
        "open_time": 1000,
        "open": 10.0,
        "high": 11.0,
        "low": 9.0,
        "close": 10.5,
        "volume": 25.0,
        "close_time": 1299,
    }]
    ws = {
        "open_time": 1000,
        "open": 10.0,
        "high": 12.0,
        "low": 8.0,
        "close": 11.0,
        "volume": 40.0,
        "close_time": 1299,
        "is_closed": True,
    }

    result = compare_rest_ws_candle(
        rest,
        ws,
        rest_snapshot_fetched_at=1.298,
    )

    assert result["status"] == "REST_SNAPSHOT_PREDATES_CANDLE_CLOSE"
    assert result["open_time"] == 1000
    assert result["rest_snapshot_fetched_at"] == 1.298
    assert result["ws_close_time"] == 1299


def test_normalize_cached_rest_snapshot_preserves_stale_snapshot_timestamp():
    from types import SimpleNamespace

    from core.binance_rest_ws_comparison import normalize_cached_rest_snapshot

    snapshot = SimpleNamespace(
        fetched_at=1_298.0,
        payload=[{
            "open_time": 1000,
            "open": 10.0,
            "high": 11.0,
            "low": 9.0,
            "close": 10.5,
            "volume": 25.0,
            "close_time": 1299,
        }],
    )

    candles, fetched_at = normalize_cached_rest_snapshot(snapshot)

    assert candles[0]["open_time"] == 1000
    assert fetched_at == 1298.0


def test_compare_rest_ws_no_rest_match_reports_window_context():
    rest = [
        {
            "open_time": 2000,
            "open": 20.0,
            "high": 21.0,
            "low": 19.0,
            "close": 20.5,
            "volume": 50.0,
            "close_time": 2299,
        },
        {
            "open_time": 3000,
            "open": 30.0,
            "high": 31.0,
            "low": 29.0,
            "close": 30.5,
            "volume": 60.0,
            "close_time": 3299,
        },
    ]
    ws = {
        "open_time": 1000,
        "open": 10.0,
        "high": 11.0,
        "low": 9.0,
        "close": 10.5,
        "volume": 25.0,
        "close_time": 1299,
        "is_closed": True,
    }

    result = compare_rest_ws_candle(
        rest,
        ws,
        rest_snapshot_fetched_at=1_400.0,
    )

    assert result["status"] == "NO_REST_MATCH"
    assert result["rest_candle_count"] == 2
    assert result["rest_snapshot_fetched_at"] == 1_400.0
    assert result["ws_close_time"] == 1299
    assert result["rest_min_open_time"] == 2000
    assert result["rest_max_open_time"] == 3000
    assert result["rest_window_relation"] == "WS_OLDER_THAN_REST_WINDOW"


def test_compare_rest_ws_no_rest_match_reports_empty_rest_window():
    ws = {
        "open_time": 1000,
        "open": 10.0,
        "high": 11.0,
        "low": 9.0,
        "close": 10.5,
        "volume": 25.0,
        "close_time": 1299,
        "is_closed": True,
    }

    result = compare_rest_ws_candle([], ws)

    assert result["status"] == "NO_REST_MATCH"
    assert result["rest_candle_count"] == 0
    assert result["rest_window_relation"] == "REST_EMPTY"
