from core.paper_outcome_analysis import build_paper_outcome_analysis


def _record(
    position_id,
    *,
    symbol,
    mode,
    pnl,
    gross,
    fees,
    score,
    close_reason,
    source="BINANCE",
    pattern="BULLISH_ENGULFING",
    regime="RECOVERY",
    stop=0.8,
    reasons=None,
):
    return {
        "position_id": position_id,
        "symbol": symbol,
        "trade_mode": mode,
        "realized_pnl": pnl,
        "gross_pnl": gross,
        "fees": fees,
        "close_reason": close_reason,
        "market_data_source": source,
        "strategy": {
            "score": score,
            "scalp_score": score if mode == "SCALP" else None,
            "swing_score": score if mode == "SWING" else None,
            "pattern": pattern,
        },
        "regime": {"market": regime},
        "entry_forensics": {
            "stop_distance_valid": stop is not None,
            "stop_distance_percent": stop,
            "recovery_trigger_reasons": ["5M_RECOVERY_CONFIRMATION"] if reasons else [],
        },
        "entry_v2": {"reasons": reasons or []},
        "holding_seconds": 600,
        "entry_context_available": True,
    }


def test_analysis_reports_net_after_fees_and_win_loss_asymmetry():
    records = [
        _record("1", symbol="BTCUSDT", mode="SWING", pnl=0.25, gross=0.35, fees=0.10,
                score=88, close_reason="TRAILING_STOP", pattern="ENGULFING", stop=0.8),
        _record("2", symbol="ETHUSDT", mode="SWING", pnl=-0.60, gross=-0.50, fees=0.10,
                score=81, close_reason="STOP_LOSS", pattern="MORNING_STAR", stop=1.2),
        _record("3", symbol="ARBUSDT", mode="SCALP", pnl=-0.40, gross=-0.30, fees=0.10,
                score=65, close_reason="STOP_LOSS", pattern="BREAKOUT", stop=0.6,
                source="BYBIT", reasons=["5M_RECOVERY_CONFIRMATION"]),
    ]

    result = build_paper_outcome_analysis(records)

    assert result["record_count"] == 3
    assert result["totals"]["wins"] == 1
    assert result["totals"]["losses"] == 2
    assert result["totals"]["win_rate_percent"] == 33.33
    assert result["totals"]["gross_pnl"] == -0.45
    assert result["totals"]["fees"] == 0.3
    assert result["totals"]["net_pnl"] == -0.75
    assert result["totals"]["avg_win_net_pnl"] == 0.25
    assert result["totals"]["avg_loss_net_pnl"] == -0.5
    assert result["totals"]["profit_factor"] == 0.25
    assert result["by_trade_mode"]["SWING"]["records"] == 2
    assert result["by_market_data_source"]["BYBIT"]["net_pnl"] == -0.4
    assert result["by_close_reason"]["STOP_LOSS"]["losses"] == 2


def test_score_bands_are_relative_to_preserved_mode_thresholds():
    records = [
        _record("s1", symbol="AUSDT", mode="SCALP", pnl=-0.1, gross=0.0, fees=0.1,
                score=65, close_reason="STOP_LOSS"),
        _record("s2", symbol="BUSDT", mode="SCALP", pnl=0.2, gross=0.3, fees=0.1,
                score=72, close_reason="TRAILING_STOP"),
        _record("w1", symbol="CUSDT", mode="SWING", pnl=-0.1, gross=0.0, fees=0.1,
                score=80, close_reason="STOP_LOSS"),
        _record("w2", symbol="DUSDT", mode="SWING", pnl=0.2, gross=0.3, fees=0.1,
                score=92, close_reason="TRAILING_STOP"),
    ]

    result = build_paper_outcome_analysis(records)

    assert result["by_entry_score_band"]["AT_THRESHOLD_TO_PLUS4"]["records"] == 2
    assert result["by_entry_score_band"]["THRESHOLD_PLUS5_TO_PLUS9"]["records"] == 1
    assert result["by_entry_score_band"]["THRESHOLD_PLUS10_OR_MORE"]["records"] == 1


def test_analysis_marks_missing_data_without_leaking_trade_identifiers():
    result = build_paper_outcome_analysis([
        {"position_id": "SECRET-POS-123", "realized_pnl": 0.2, "trade_mode": "", "strategy": {}},
        {"symbol": "ETHUSDT", "trade_mode": "SWING", "realized_pnl": None},
    ])

    assert result["data_quality"]["records_missing_trade_mode"] == 1
    assert result["data_quality"]["records_missing_market_data_source"] == 2
    assert result["totals"]["records_missing_net_pnl"] == 1
    assert "SECRET-POS-123" not in repr(result)


def test_market_regime_falls_back_to_captured_mtf_context():
    record = _record(
        "regime-fallback", symbol="BTCUSDT", mode="SCALP", pnl=-0.2, gross=-0.1,
        fees=0.1, score=68, close_reason="STOP_LOSS", regime=None,
    )
    record["regime"] = {
        "market": None,
        "symbol": None,
        "mtf_bias": "BEARISH",
        "mtf_net": -2.0,
    }

    result = build_paper_outcome_analysis([record])

    assert result["by_market_regime"]["BEAR"]["records"] == 1
    assert result["data_quality"]["records_missing_market_regime"] == 0


def test_regime_prefers_explicit_symbol_regime_and_reports_unknown_when_context_absent():
    known = _record(
        "known", symbol="ETHUSDT", mode="SCALP", pnl=0.1, gross=0.2, fees=0.1,
        score=70, close_reason="TRAILING_STOP", regime=None,
    )
    known["regime"] = {"market": "UNKNOWN", "symbol": "RECOVERY", "mtf_net": -1.0}
    unknown = _record(
        "unknown", symbol="ADAUSDT", mode="SCALP", pnl=-0.1, gross=0.0, fees=0.1,
        score=65, close_reason="STOP_LOSS", regime=None,
    )
    unknown["regime"] = {"market": None, "symbol": None}

    result = build_paper_outcome_analysis([known, unknown])

    assert result["by_market_regime"]["RECOVERY"]["records"] == 1
    assert result["by_market_regime"]["UNKNOWN"]["records"] == 1
    assert result["data_quality"]["records_missing_market_regime"] == 1


def test_reason_breakdowns_preserve_source_provenance():
    record = _record(
        "reason-provenance", symbol="ARBUSDT", mode="SCALP", pnl=-0.3, gross=-0.2,
        fees=0.1, score=69, close_reason="STOP_LOSS", reasons=["ENTRY_V2_SIGNAL"],
    )
    record["entry_forensics"]["recovery_trigger_reasons"] = [
        "5M_PRICE_RECOVERY",
        "ENTRY_V2_TAG_LEAKED_INTO_TRIGGER_LIST",
    ]
    record["strategy"]["scalp_gate_reasons"] = ["SCALP_GATE_TAG"]

    result = build_paper_outcome_analysis([record])

    assert result["by_entry_v2_reason"]["ENTRY_V2_SIGNAL"]["records"] == 1
    assert result["by_recovery_trigger_reason"]["5M_PRICE_RECOVERY"]["records"] == 1
    assert "ENTRY_V2_TAG_LEAKED_INTO_TRIGGER_LIST" not in result["by_recovery_trigger_reason"]
    assert result["by_scalp_gate_reason"]["SCALP_GATE_TAG"]["records"] == 1
    assert result["data_quality"]["records_with_unrecognized_recovery_trigger_reasons"] == 1
    # Legacy key remains backward-compatible and retains the raw combined tags.
    assert result["by_entry_reason"]["ENTRY_V2_SIGNAL"]["records"] == 1
    assert result["by_entry_reason"]["ENTRY_V2_TAG_LEAKED_INTO_TRIGGER_LIST"]["records"] == 1
    assert result["by_entry_reason"]["SCALP_GATE_TAG"]["records"] == 1


def test_paper_outcome_analysis_endpoint_returns_aggregates_only(monkeypatch):
    import shadow_main

    class FakeStore:
        last_error = None

        def read_all(self):
            return [
                {
                    "position_id": "POS-SECRET-1",
                    "symbol": "BTCUSDT",
                    "trade_mode": "SWING",
                    "realized_pnl": 0.25,
                    "gross_pnl": 0.35,
                    "fees": 0.10,
                    "market_data_source": "BINANCE",
                    "close_reason": "TRAILING_STOP",
                    "strategy": {"score": 88, "swing_score": 88, "pattern": "ENGULFING"},
                    "entry_forensics": {"stop_distance_valid": True, "stop_distance_percent": 0.8},
                    "entry_context_available": True,
                }
            ]

    monkeypatch.setattr(shadow_main, "_paper_outcome_store", FakeStore())
    response = shadow_main.app.test_client().get("/paper/outcome-analysis")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["available"] is True
    assert payload["mode"] == "PAPER"
    assert payload["totals"]["records"] == 1
    assert payload["totals"]["net_pnl"] == 0.25
    assert payload["by_trade_mode"]["SWING"]["wins"] == 1
    assert "POS-SECRET-1" not in repr(payload)


def test_paper_outcome_analysis_endpoint_reports_store_read_failure(monkeypatch):
    import shadow_main

    class FailedStore:
        last_error = None

        def read_all(self):
            self.last_error = "DatabaseUnavailable: private connection detail"
            return []

    monkeypatch.setattr(shadow_main, "_paper_outcome_store", FailedStore())
    response = shadow_main.app.test_client().get("/paper/outcome-analysis")

    assert response.status_code == 503
    payload = response.get_json()
    assert payload["available"] is False
    assert payload["reason"] == "PAPER_OUTCOME_READ_FAILED"
    assert "private connection detail" not in repr(payload)

def test_analysis_exposes_mode_source_close_and_schema_cohorts():
    scalp_bybit_stop = _record(
        "cross-1", symbol="BTCUSDT", mode="SCALP", pnl=-0.6, gross=-0.5,
        fees=0.1, score=68, close_reason="STOP_LOSS", source="BYBIT",
    )
    scalp_binance_trail = _record(
        "cross-2", symbol="ETHUSDT", mode="SCALP", pnl=0.3, gross=0.4,
        fees=0.1, score=72, close_reason="TRAILING_STOP", source="BINANCE",
    )
    swing_bybit_stop = _record(
        "cross-3", symbol="SOLUSDT", mode="SWING", pnl=-0.5, gross=-0.4,
        fees=0.1, score=84, close_reason="STOP_LOSS", source="BYBIT",
    )
    swing_binance_trail = _record(
        "cross-4", symbol="ADAUSDT", mode="SWING", pnl=0.4, gross=0.5,
        fees=0.1, score=90, close_reason="TRAILING_STOP", source="BINANCE",
    )

    scalp_bybit_stop.update({
        "schema_version": 2,
        "execution_market_data_source": "BINANCE",
    })
    scalp_binance_trail.update({
        "schema_version": 2,
        "execution_market_data_source": "BINANCE",
    })
    swing_bybit_stop.update({
        "schema_version": 1,
        "execution_market_data_source": "BYBIT",
    })
    # Model an older row that predates versioned entry/source attribution.
    swing_binance_trail["execution_market_data_source"] = "UNKNOWN"

    result = build_paper_outcome_analysis([
        scalp_bybit_stop,
        scalp_binance_trail,
        swing_bybit_stop,
        swing_binance_trail,
    ])

    assert result["by_trade_mode_and_market_data_source"]["SCALP::BYBIT"]["records"] == 1
    assert result["by_trade_mode_and_market_data_source"]["SCALP::BYBIT"]["net_pnl"] == -0.6
    assert result["by_trade_mode_and_market_data_source"]["SWING::BINANCE"]["records"] == 1
    assert result["by_trade_mode_and_close_reason"]["SCALP::STOP_LOSS"]["records"] == 1
    assert result["by_trade_mode_and_close_reason"]["SWING::TRAILING_STOP"]["records"] == 1
    assert result["by_trade_mode_and_execution_market_data_source"]["SWING::BYBIT"]["records"] == 1
    assert result["by_evidence_schema_version"]["2"]["records"] == 2
    assert result["by_evidence_schema_version"]["1"]["records"] == 1
    assert result["by_evidence_schema_version"]["UNKNOWN"]["records"] == 1
    assert result["data_quality"]["records_missing_schema_version"] == 1
    assert result["data_quality"]["records_missing_execution_market_data_source"] == 1

