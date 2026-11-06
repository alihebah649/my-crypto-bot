from core.hosted_paper_lab_report import format_hosted_lab_daily_report


def _outcome(symbol, mode, pnl, close_reason):
    return {
        "symbol": symbol,
        "trade_mode": mode,
        "realized_pnl": pnl,
        "gross_pnl": pnl + 0.10,
        "fees": 0.10,
        "close_reason": close_reason,
        "market_data_source": "BYBIT",
        "opened_at_utc": "2026-11-05T08:00:00+00:00",
        "closed_at_utc": "2026-11-05T09:00:00+00:00",
        "strategy": {"score": 81, "swing_score": 81},
    }


def test_hosted_lab_report_is_venue_scoped_and_includes_after_fee_metrics():
    report = format_hosted_lab_daily_report(
        "BYBIT",
        "2026-11-05",
        [
            _outcome("XRPUSDT", "SWING", 0.42, "TRAILING_STOP"),
            _outcome("LTCUSDT", "SWING", -0.44, "STOP_LOSS"),
            _outcome("BTCUSDT", "SCALP", -0.29, "STOP_LOSS"),
        ],
    )

    assert "BOT: BYBIT PAPER LAB" in report
    assert "VENUE: BYBIT SPOT ONLY" in report
    assert "XRP" in report and "LTC" in report and "BTC" in report
    assert "الصفقات: 3 | ربح: 1 | خسارة: 2" in report
    assert "صافي بعد الرسوم: -0.31$" in report
    assert "STOP_LOSS" in report and "TRAILING_STOP" in report
    assert report.endswith("PAPER ONLY")
    assert "position_id" not in report


def test_hosted_lab_report_handles_empty_day_without_inventing_pnl():
    report = format_hosted_lab_daily_report("OKX", "2026-11-06", [])

    assert "BOT: OKX PAPER LAB" in report
    assert "لا توجد صفقات مغلقة" in report
    assert "الصفقات: 0 | ربح: 0 | خسارة: 0" in report
    assert "صافي بعد الرسوم: —" in report
    assert report.endswith("PAPER ONLY")


def test_hosted_lab_report_rejects_other_venues():
    try:
        format_hosted_lab_daily_report("BINANCE", "2026-11-05", [])
    except ValueError as exc:
        assert "unsupported hosted Paper lab venue" in str(exc)
    else:
        raise AssertionError("unsupported venue should be rejected")



def test_shadow_main_queries_each_lab_store_using_aden_local_day(monkeypatch):
    from types import SimpleNamespace
    from zoneinfo import ZoneInfo
    import shadow_main

    class FakeStore:
        last_error = None

        def __init__(self, records):
            self.records = records
            self.query = None

        def read_time_range(self, field, start, end):
            self.query = (field, start, end)
            return self.records

    bybit_store = FakeStore([_outcome("XRPUSDT", "SWING", 0.42, "TRAILING_STOP")])
    okx_store = FakeStore([_outcome("LTCUSDT", "SWING", -0.44, "STOP_LOSS")])
    runner = SimpleNamespace(labs={
        "BYBIT": SimpleNamespace(outcomes=bybit_store),
        "OKX": SimpleNamespace(outcomes=okx_store),
    })
    monkeypatch.setattr(shadow_main, "_hosted_paper_lab_runner", runner, raising=False)
    monkeypatch.setattr(shadow_main._legacy, "REPORT_TIMEZONE", ZoneInfo("Asia/Aden"))

    bybit_report = shadow_main._hosted_lab_daily_report_for_venue("BYBIT", "2026-11-05")
    okx_report = shadow_main._hosted_lab_daily_report_for_venue("OKX", "2026-11-05")

    expected_query = (
        "closed_at_utc",
        "2026-11-04T21:00:00+00:00",
        "2026-11-05T21:00:00+00:00",
    )
    assert bybit_store.query == expected_query
    assert okx_store.query == expected_query
    assert "BOT: BYBIT PAPER LAB" in bybit_report
    assert "BOT: OKX PAPER LAB" in okx_report
    assert "XRP" in bybit_report and "XRP" not in okx_report
    assert "LTC" in okx_report and "LTC" not in bybit_report
