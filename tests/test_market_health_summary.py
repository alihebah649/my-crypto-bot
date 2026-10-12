from core.market_health_summary import build_paper_market_health_summary


def _healthy_binance_relay():
    return {
        "available": True,
        "mode": "PAPER_AUTHORITATIVE_BINANCE_WS",
        "transport": "EXTERNAL_RELAY",
        "connected": True,
        "event_stream_healthy": True,
        "symbols_with_latest_kline": 88,
        "expected_kline_streams": 88,
        "tickers_with_latest": 22,
        "expected_tickers": 22,
        "last_event_age_seconds": 0.02,
        "runtime_integration": {
            "kline_history_keys": 88,
            "kline_history_rows": 8448,
        },
    }


def test_market_health_reports_active_relay_when_local_kline_cache_is_empty():
    result = build_paper_market_health_summary(
        scored_symbol_count=22,
        symbol_count=22,
        local_kline_cache_entries=0,
        venue="BINANCE",
        websocket_snapshot=_healthy_binance_relay(),
    )

    assert result["state"] == "MARKET DATA UP"
    assert "Active WebSocket feed: BINANCE / EXTERNAL_RELAY — HEALTHY" in result["detail"]
    assert "Kline streams: 88/88; Tickers: 22/22" in result["detail"]
    assert "Local Kline fallback cache: 0 entries" in result["detail"]
    assert "WebSocket candle history: 88 keys / 8448 rows" in result["detail"]


def test_market_health_marks_disconnected_feed_degraded_even_if_scores_remain():
    snapshot = _healthy_binance_relay()
    snapshot["connected"] = False

    result = build_paper_market_health_summary(
        scored_symbol_count=22,
        symbol_count=22,
        local_kline_cache_entries=0,
        venue="BINANCE",
        websocket_snapshot=snapshot,
    )

    assert result["state"] == "MARKET DATA DEGRADED"
    assert "Active WebSocket feed: BINANCE / EXTERNAL_RELAY — DEGRADED" in result["detail"]


def test_market_health_marks_missing_stream_coverage_degraded():
    snapshot = _healthy_binance_relay()
    snapshot["tickers_with_latest"] = 21

    result = build_paper_market_health_summary(
        scored_symbol_count=22,
        symbol_count=22,
        local_kline_cache_entries=6,
        venue="BINANCE",
        websocket_snapshot=snapshot,
    )

    assert result["state"] == "MARKET DATA DEGRADED"
    assert "Tickers: 21/22" in result["detail"]


def test_market_health_is_down_when_no_symbols_are_scored():
    result = build_paper_market_health_summary(
        scored_symbol_count=0,
        symbol_count=22,
        local_kline_cache_entries=0,
        venue="BINANCE",
        websocket_snapshot=_healthy_binance_relay(),
    )

    assert result["state"] == "MARKET DATA DOWN"
