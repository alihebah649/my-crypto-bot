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
