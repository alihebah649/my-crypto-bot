from core.paper_entry_outcome_forensics import build_linked_entry_outcome_analysis


def test_main_outcome_joins_to_entry_capture_by_capture_id_and_calculates_mfe():
    capture = {
        "capture_id": "cap-main-1",
        "captured_at": "2026-11-05T08:00:00+00:00",
        "symbol": "BTCUSDT",
        "legacy_result": {
            "trade_mode": "SCALP",
            "score": 66,
            "scalp_score": 66,
            "atr": 1.5,
            "rsi5m": 38.0,
            "volume_ratio_5m": 1.4,
        },
        "entry_scenario": {
            "trade_mode": "SCALP",
            "setup_type": "REVERSAL",
            "risk": {
                "target_price": 106.0,
                "target_status": "VALID",
                "reward_risk": 2.0,
            },
        },
        "v2_decision": {
            "approved": False,
            "decision": "REJECT",
            "failed_gate": "NO_RECLAIM",
        },
    }
    outcome = {
        "position_id": "POS-MAIN-1",
        "symbol": "BTCUSDT",
        "trade_mode": "SCALP",
        "entry_price": 100.0,
        "entry_stop_loss": 97.0,
        "entry_forensics": {
            "stop_distance_source": "ENTRY_METADATA",
            "atr_percent_of_entry": 1.5,
        },
        "quantity": 1.0,
        "gross_pnl": -1.0,
        "realized_pnl": -1.3,
        "fees": 0.3,
        "highest_price": 103.5,
        "max_profit_percent": 3.5,
        "close_reason": "STOP_LOSS",
        "entry_v2": {"capture_id": "cap-main-1"},
        "regime": {"market": "BULLISH"},
    }

    result = build_linked_entry_outcome_analysis("MAIN", [outcome], [capture])

    assert result["coverage"]["matched_closed_trades"] == 1
    assert result["coverage"]["unmatched_outcomes"] == 0
    assert result["overall"]["losses"] == 1
    assert result["overall"]["net_pnl_after_fees"] == -1.3
    assert result["overall"]["average_expected_rr"] == 2.0
    assert result["overall"]["average_realized_r_multiple_net"] == -0.4333
    assert result["overall"]["losers_with_positive_net_favorable_excursion"] == 1
    assert result["losers_with_positive_net_favorable_excursion"][0]["net_mfe"] == 3.2
    assert result["by_entry_v2_shadow_approval"]["FALSE"]["closed_trades"] == 1
    assert result["worst_trades"][0]["entry_v2_failed_gate_shadow"] == "NO_RECLAIM"


def test_hosted_lab_outcome_joins_to_capture_by_position_id():
    capture = {
        "capture_id": "lab-capture-1",
        "position_id": "POS-BYBIT-1",
        "symbol": "ETHUSDT",
        "candidate": {
            "symbol": "ETHUSDT",
            "trade_mode": "SWING",
            "score": 82,
            "entry_price": 50.0,
            "stop_loss": 49.5,
            "market_data_source": "BYBIT",
        },
        "legacy_result": {"atr": 0.25, "rsi5m": 42.0},
        "entry_economics": {
            "reward_risk": 1.5,
            "risk_percent": 1.0,
            "net_reward_percent": 1.3,
        },
        "v2_decision": {"approved": True, "decision": "APPROVE"},
    }
    outcome = {
        "position_id": "POS-BYBIT-1",
        "symbol": "ETHUSDT",
        "trade_mode": "SWING",
        "entry_price": 50.0,
        "entry_stop_loss": 49.4,
        "entry_forensics": {"stop_distance_source": "POSITION_CURRENT_STOP_FALLBACK"},
        "quantity": 10.0,
        "gross_pnl": -0.5,
        "realized_pnl": -0.6,
        "fees": 0.1,
        "highest_price": 50.3,
        "close_reason": "STOP_LOSS",
    }

    result = build_linked_entry_outcome_analysis("BYBIT", [outcome], [capture])

    assert result["coverage"]["matched_closed_trades"] == 1
    assert result["by_trade_mode"]["SWING"]["closed_trades"] == 1
    assert result["overall"]["average_stop_atr_multiple"] == 2.0
    assert result["overall"]["average_expected_net_rr_after_fees"] == 1.3
    assert result["overall"]["losers_with_positive_net_favorable_excursion"] == 1


def test_unmatched_outcome_is_reported_and_never_filled_from_unrelated_capture():
    outcome = {
        "position_id": "POS-UNKNOWN",
        "symbol": "XRPUSDT",
        "trade_mode": "SCALP",
        "realized_pnl": -0.4,
    }
    unrelated_capture = {
        "capture_id": "capture-other",
        "position_id": "POS-OTHER",
        "symbol": "BTCUSDT",
    }

    result = build_linked_entry_outcome_analysis("OKX", [outcome], [unrelated_capture])

    assert result["coverage"]["matched_closed_trades"] == 0
    assert result["coverage"]["unmatched_outcomes"] == 1
    assert result["overall"]["closed_trades"] == 0
    assert result["coverage"]["unmatched_entry_captures"] == 1


def test_forensics_rejects_unsupported_venue():
    try:
        build_linked_entry_outcome_analysis("BINANCE", [], [])
    except ValueError as exc:
        assert "unsupported Paper venue" in str(exc)
    else:
        raise AssertionError("unsupported venue should be rejected")



def test_shadow_main_forensics_reads_only_captures_referenced_by_closed_outcomes(monkeypatch):
    from types import SimpleNamespace
    import shadow_main

    class FakeStore:
        def __init__(self, outcomes=None, captures=None):
            self.outcomes = list(outcomes or [])
            self.captures = list(captures or [])
            self.last_error = None
            self.requested = None

        def read_time_range(self, timestamp_field, _start, _end):
            assert timestamp_field == "closed_at_utc"
            return list(self.outcomes)

        def read_by_identity_keys(self, keys):
            self.requested = set(keys)
            return [
                row for row in self.captures
                if row.get("capture_id") in self.requested
            ]

        def read_by_payload_values(self, field, values):
            assert field == "position_id"
            self.requested = set(values)
            return [
                row for row in self.captures
                if row.get("position_id") in self.requested
            ]

        def read_all(self):
            raise AssertionError("forensics must never load the full capture history")

    main_outcome = {
        "position_id": "POS-MAIN-1",
        "symbol": "BTCUSDT",
        "trade_mode": "SCALP",
        "entry_price": 100.0,
        "entry_stop_loss": 99.0,
        "entry_forensics": {"stop_distance_source": "ENTRY_METADATA"},
        "quantity": 1.0,
        "gross_pnl": 0.2,
        "realized_pnl": 0.0,
        "fees": 0.2,
        "highest_price": 100.5,
        "close_reason": "STOP_LOSS",
        "entry_v2": {"capture_id": "CAP-MAIN-1"},
    }
    main_capture = {
        "capture_id": "CAP-MAIN-1",
        "symbol": "BTCUSDT",
        "legacy_result": {"trade_mode": "SCALP", "scalp_score": 66, "atr": 0.5},
        "entry_scenario": {"trade_mode": "SCALP", "risk": {"reward_risk": 2.0}},
        "v2_decision": {"approved": True, "decision": "APPROVE"},
    }
    bybit_outcome = {
        "position_id": "POS-BYBIT-1",
        "symbol": "ETHUSDT",
        "trade_mode": "SWING",
        "entry_price": 50.0,
        "entry_stop_loss": 49.5,
        "entry_forensics": {"stop_distance_source": "POSITION_CURRENT_STOP_FALLBACK"},
        "quantity": 1.0,
        "gross_pnl": -0.6,
        "realized_pnl": -0.8,
        "fees": 0.2,
        "highest_price": 50.2,
        "close_reason": "STOP_LOSS",
    }
    bybit_capture = {
        "capture_id": "CAP-BYBIT-1",
        "position_id": "POS-BYBIT-1",
        "symbol": "ETHUSDT",
        "candidate": {
            "symbol": "ETHUSDT",
            "trade_mode": "SWING",
            "score": 81,
            "entry_price": 50.0,
            "stop_loss": 49.5,
        },
        "legacy_result": {"atr": 0.25},
        "entry_economics": {
            "reward_risk": 1.5,
            "risk_percent": 1.0,
            "net_reward_percent": 1.2,
        },
    }
    okx_outcome = {
        "position_id": "POS-OKX-1",
        "symbol": "XRPUSDT",
        "trade_mode": "SWING",
        "entry_price": 1.0,
        "entry_stop_loss": 0.99,
        "entry_forensics": {"stop_distance_source": "POSITION_CURRENT_STOP_FALLBACK"},
        "quantity": 1.0,
        "gross_pnl": 0.3,
        "realized_pnl": 0.1,
        "fees": 0.2,
        "highest_price": 1.4,
        "close_reason": "TRAILING_STOP",
    }
    okx_capture = {
        "capture_id": "CAP-OKX-1",
        "position_id": "POS-OKX-1",
        "symbol": "XRPUSDT",
        "candidate": {
            "symbol": "XRPUSDT",
            "trade_mode": "SWING",
            "score": 84,
            "entry_price": 1.0,
            "stop_loss": 0.99,
        },
        "legacy_result": {"atr": 0.005},
        "entry_economics": {
            "reward_risk": 1.8,
            "risk_percent": 1.0,
            "net_reward_percent": 1.5,
        },
    }

    main_outcome_store = FakeStore([main_outcome])
    main_capture_store = FakeStore(captures=[main_capture, {"capture_id": "UNRELATED-LARGE-CAPTURE"}])
    bybit = SimpleNamespace(
        outcomes=FakeStore([bybit_outcome]),
        entry_captures=FakeStore(captures=[bybit_capture, {"capture_id": "UNRELATED", "position_id": "POS-OTHER"}]),
    )
    okx = SimpleNamespace(
        outcomes=FakeStore([okx_outcome]),
        entry_captures=FakeStore(captures=[okx_capture]),
    )

    monkeypatch.setattr(shadow_main, "_paper_outcome_store", main_outcome_store)
    monkeypatch.setattr(
        shadow_main,
        "_entry_v2_runtime_capture",
        SimpleNamespace(capture_store=main_capture_store),
    )
    monkeypatch.setattr(
        shadow_main,
        "_hosted_paper_lab_runner",
        SimpleNamespace(labs={"BYBIT": bybit, "OKX": okx}),
    )
    monkeypatch.setattr(
        shadow_main,
        "_paper_forensics_time_range",
        lambda: ("2026-08-08T00:00:00+00:00", "2026-11-06T00:00:00+00:00"),
    )

    report = shadow_main._build_linked_entry_outcome_forensics()

    assert report["available"] is True
    assert main_capture_store.requested == {"CAP-MAIN-1"}
    assert bybit.entry_captures.requested == {"POS-BYBIT-1"}
    assert okx.entry_captures.requested == {"POS-OKX-1"}
    assert report["venues"]["MAIN"]["coverage"]["matched_closed_trades"] == 1
    assert report["venues"]["BYBIT"]["coverage"]["matched_closed_trades"] == 1
    assert report["venues"]["OKX"]["coverage"]["matched_closed_trades"] == 1
