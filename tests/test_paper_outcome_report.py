from core.paper_outcome_report import format_paper_outcome_report


def test_daily_report_formats_closed_outcome_metrics_and_breakdowns():
    analysis = {
        "record_count": 3,
        "totals": {
            "records": 3,
            "wins": 1,
            "losses": 2,
            "flat": 0,
            "net_pnl": -0.75,
            "win_rate_percent": 33.33,
            "profit_factor": 0.25,
            "avg_win_net_pnl": 0.25,
            "avg_loss_net_pnl": -0.50,
            "fees": 0.30,
            "records_missing_net_pnl": 0,
        },
        "by_trade_mode": {
            "SCALP": {"records": 1, "wins": 0, "losses": 1, "net_pnl": -0.40},
            "SWING": {"records": 2, "wins": 1, "losses": 1, "net_pnl": -0.35},
        },
        "by_market_data_source": {
            "BYBIT": {"records": 1, "wins": 0, "losses": 1, "net_pnl": -0.40},
            "BINANCE": {"records": 2, "wins": 1, "losses": 1, "net_pnl": -0.35},
        },
        "by_close_reason": {
            "STOP_LOSS": {"records": 2, "wins": 0, "losses": 2, "net_pnl": -1.00},
            "TRAILING_STOP": {"records": 1, "wins": 1, "losses": 0, "net_pnl": 0.25},
        },
        "by_entry_score_band": {
            "AT_THRESHOLD_TO_PLUS4": {"records": 2, "wins": 0, "losses": 2, "net_pnl": -0.50},
            "THRESHOLD_PLUS10_OR_MORE": {"records": 1, "wins": 1, "losses": 0, "net_pnl": 0.25},
        },
        "data_quality": {"records_missing_entry_context": 0},
    }

    report = format_paper_outcome_report(analysis)

    assert "الصفقات: 3 | ربح: 1 | خسارة: 2 | تعادل: 0" in report
    assert "صافي بعد الرسوم: -0.75$" in report
    assert "SCALP" in report
    assert "SWING" in report
    assert "STOP_LOSS" in report
    assert "العتبة إلى +4" in report
    assert "Profit Factor: 0.25" in report
    assert "position_id" not in report


def test_daily_report_handles_empty_day_without_inventing_profit():
    report = format_paper_outcome_report({
        "record_count": 0,
        "totals": {
            "records": 0,
            "wins": 0,
            "losses": 0,
            "flat": 0,
            "net_pnl": None,
            "win_rate_percent": None,
            "profit_factor": None,
            "avg_win_net_pnl": None,
            "avg_loss_net_pnl": None,
            "fees": None,
        },
        "data_quality": {},
    })

    assert "الصفقات: 0" in report
    assert "صافي بعد الرسوم: —" in report
    assert "0.00$" not in report
