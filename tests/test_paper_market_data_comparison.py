from core.paper_market_data_comparison import compare_paper_outcomes_by_market_data_source


def test_compare_paper_outcomes_by_source():
    records = [
        {"market_data_source": "BINANCE", "realized_pnl": 0.20, "fees": 0.10,
         "entry_forensics": {"stop_distance_valid": True, "stop_distance_percent": 1.0}},
        {"market_data_source": "BINANCE", "realized_pnl": -0.40, "fees": 0.10,
         "entry_forensics": {"stop_distance_valid": True, "stop_distance_percent": 0.5}},
        {"market_data_source": "BYBIT", "realized_pnl": 0.30, "fees": 0.10,
         "entry_forensics": {"stop_distance_valid": True, "stop_distance_percent": 1.5}},
        {"strategy": {"market_data_source": "BYBIT"}, "realized_pnl": -0.10, "fees": 0.10,
         "entry_forensics": {"stop_distance_valid": False}},
        {"realized_pnl": 1.0},
    ]

    result = compare_paper_outcomes_by_market_data_source(records)

    assert result["total_records"] == 5
    assert result["unknown_source_records"] == 1
    assert result["sources"]["BINANCE"]["records"] == 2
    assert result["sources"]["BINANCE"]["wins"] == 1
    assert result["sources"]["BINANCE"]["losses"] == 1
    assert result["sources"]["BINANCE"]["net_pnl"] == -0.2
    assert result["sources"]["BYBIT"]["records"] == 2
    assert result["sources"]["BYBIT"]["wins"] == 1
    assert result["sources"]["BYBIT"]["losses"] == 1
    assert result["sources"]["BYBIT"]["net_pnl"] == 0.2
    assert result["sources"]["BYBIT"]["avg_stop_distance_percent"] == 1.5
