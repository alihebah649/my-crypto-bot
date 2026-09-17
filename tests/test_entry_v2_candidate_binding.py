from __future__ import annotations

from types import SimpleNamespace

from engine.entry_v2_runtime_capture import install


def _candle(value: float) -> dict:
    return {
        "open": value,
        "high": value + 0.5,
        "low": value - 0.5,
        "close": value + 0.2,
        "volume": 100.0,
    }


def test_candidate_is_captured_before_position_add_and_bound_by_id(tmp_path):
    result = {
        "symbol": "TESTUSDT",
        "signal": "BUY",
        "trade_mode": "SCALP",
        "scalp_signal": "BUY",
        "swing_signal": "HOLD",
        "score": 72,
        "scalp_score": 72,
        "swing_score": 50,
        "price": 100.0,
        "atr": 1.0,
        "scalp_confirmed_reversal": True,
        "scalp_recovery_confirmation": False,
        "scalp_reasons": ["15M_BOLLINGER_NEAR_SUPPORT"],
        "volume_ratio_5m": 1.2,
    }

    class Legacy:
        latest_scores = {}

        def fetch_strategy_data(self):
            candles = [_candle(100 + i) for i in range(12)]
            return (
                {"TESTUSDT": {"lastPrice": "100", "bidPrice": "99.99", "askPrice": "100.01"}},
                {"TESTUSDT": candles},
                {"TESTUSDT": candles},
            )

        def score_symbol(self, symbol, ticker, candles_15m, candles_5m):
            self.latest_scores[symbol] = dict(result)
            return dict(result)

    added = []

    class Repository:
        def add(self, position):
            added.append(position)

    runtime = SimpleNamespace(
        persistence_dir=str(tmp_path),
        repository=Repository(),
        last_entry_diagnostics={},
    )
    legacy = Legacy()
    bridge = install(
        legacy=legacy,
        runtime=runtime,
        mtf_candles={"TESTUSDT": {"1h": [_candle(200 + i) for i in range(12)], "4h": [_candle(300 + i) for i in range(12)]}},
        trading_symbols=["TESTUSDT"],
    )

    bridge.legacy.fetch_strategy_data()
    returned = bridge.legacy.score_symbol("TESTUSDT", {}, [], [])

    assert returned == result
    capture_id = bridge.latest_capture_id("TESTUSDT")
    assert capture_id

    position = SimpleNamespace(symbol="TESTUSDT", entry_metadata={}, position_id="POS-1")
    runtime.repository.add(position)

    assert added == [position]
    assert position.entry_metadata["entry_v2_shadow_capture_id"] == capture_id
    assert position.entry_metadata["entry_v2_shadow_decision"]["trade_mode"] == "SCALP"
    assert position.entry_metadata["entry_v2_shadow_target_status"] in {
        "VALID", "NO_TARGET_ABOVE_ENTRY", "NO_TARGET_MEETS_RR"
    }


def test_capture_cycle_does_not_duplicate_pre_execution_candidate(tmp_path):
    class Legacy:
        latest_scores = {
            "TESTUSDT": {
                "symbol": "TESTUSDT",
                "signal": "BUY",
                "trade_mode": "SCALP",
                "scalp_signal": "BUY",
                "swing_signal": "HOLD",
                "score": 70,
                "scalp_score": 70,
                "swing_score": 50,
                "price": 100.0,
                "atr": 1.0,
                "scalp_confirmed_reversal": True,
                "scalp_reasons": ["15M_BOLLINGER_NEAR_SUPPORT"],
                "volume_ratio_5m": 1.2,
            }
        }

        def fetch_strategy_data(self):
            candles = [_candle(100 + i) for i in range(12)]
            return (
                {"TESTUSDT": {"lastPrice": "100", "bidPrice": "99.99", "askPrice": "100.01"}},
                {"TESTUSDT": candles},
                {"TESTUSDT": candles},
            )

        def score_symbol(self, *args, **kwargs):
            return self.latest_scores["TESTUSDT"]

    runtime = SimpleNamespace(
        persistence_dir=str(tmp_path),
        repository=SimpleNamespace(add=lambda position: None),
        last_entry_diagnostics={},
    )
    bridge = install(
        legacy=Legacy(), runtime=runtime,
        mtf_candles={"TESTUSDT": {"1h": [_candle(200 + i) for i in range(12)], "4h": [_candle(300 + i) for i in range(12)]}},
        trading_symbols=["TESTUSDT"],
    )
    bridge.legacy.fetch_strategy_data()
    bridge.legacy.score_symbol("TESTUSDT", {}, [], [])
    summary = bridge.capture_cycle()

    assert summary["captured_candidates"] == 1
    assert summary["persisted_records"] == 1
    assert bridge.capture_store is not None
    assert bridge.capture_store.count() == 1


def test_runtime_summary_exposes_historical_outcomes_and_shadow_report_for_bound_positions(tmp_path):
    class Legacy:
        latest_scores = {}

        def fetch_strategy_data(self):
            candles = [_candle(100 + i) for i in range(12)]
            return (
                {"TESTUSDT": {"lastPrice": "100", "bidPrice": "99.99", "askPrice": "100.01"}},
                {"TESTUSDT": candles},
                {"TESTUSDT": candles},
            )

        def score_symbol(self, symbol, *args):
            result = {
                "symbol": symbol,
                "signal": "BUY",
                "trade_mode": "SCALP",
                "scalp_signal": "BUY",
                "swing_signal": "HOLD",
                "score": 70,
                "scalp_score": 70,
                "swing_score": 50,
                "price": 100.0,
                "atr": 1.0,
                "scalp_confirmed_reversal": True,
                "scalp_reasons": ["15M_BOLLINGER_NEAR_SUPPORT"],
                "volume_ratio_5m": 1.2,
            }
            self.latest_scores[symbol] = result
            return result

    stored_positions = []

    class Repository:
        def add(self, position):
            stored_positions.append(position)
        def get_open_positions(self):
            return [p for p in stored_positions if p.status == "OPEN"]
        def get_closed_positions(self):
            return [p for p in stored_positions if p.status == "CLOSED"]

    runtime = SimpleNamespace(
        persistence_dir=str(tmp_path),
        repository=Repository(),
        last_entry_diagnostics={},
    )
    bridge = install(
        legacy=Legacy(), runtime=runtime,
        mtf_candles={"TESTUSDT": {"1h": [_candle(200 + i) for i in range(12)], "4h": [_candle(300 + i) for i in range(12)]}},
        trading_symbols=["TESTUSDT"],
    )
    bridge.legacy.fetch_strategy_data()
    bridge.legacy.score_symbol("TESTUSDT", {}, [], [])
    capture = bridge.latest_captures()["TESTUSDT"]
    position = SimpleNamespace(
        position_id="POS-1", symbol="TESTUSDT", status="CLOSED",
        entry_metadata={"entry_v2_shadow_capture_id": capture["capture_id"], "trade_mode": "SCALP"},
        realized_pnl=-1.25, total_fees=0.2,
    )
    runtime.repository.add(position)

    summary = bridge.capture_cycle()
    outcomes = summary["historical_outcomes"]
    report = summary["shadow_report"]
    assert outcomes["matched_position_count"] == 1
    assert outcomes["unmatched_position_count"] == 0
    assert outcomes["by_decision"]["V2_APPROVED"]["losses"] + outcomes["by_decision"]["V2_REJECTED"]["losses"] == 1
    assert report["coverage"]["matched_positions"] == 1
    assert report["decision_flow"]["legacy_executed_v2_rejected"] in {0, 1}
    assert len(report["rejected_executions"]) == report["decision_flow"]["legacy_executed_v2_rejected"]
