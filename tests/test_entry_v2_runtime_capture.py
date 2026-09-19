from __future__ import annotations

from engine.entry_v2_runtime_capture import install


def _candle(value: float) -> dict:
    return {
        "open": value,
        "high": value + 0.5,
        "low": value - 0.5,
        "close": value + 0.2,
        "volume": 100.0,
    }


def test_runtime_capture_wraps_existing_fetch_and_captures_only_buy_candidates():
    class Legacy:
        def __init__(self):
            self.latest_scores = {
                "TESTUSDT": {
                    "symbol": "TESTUSDT", "signal": "BUY", "trade_mode": "SCALP",
                    "scalp_signal": "BUY", "swing_signal": "HOLD", "score": 72,
                    "scalp_score": 72, "swing_score": 51, "price": 100.0, "atr": 1.0,
                    "scalp_confirmed_reversal": False, "scalp_recovery_confirmation": True,
                    "scalp_reasons": ["15M_BOLLINGER_NEAR_SUPPORT"], "volume_ratio_5m": 1.2,
                },
                "HOLDUSDT": {
                    "symbol": "HOLDUSDT", "signal": "HOLD", "trade_mode": "NONE",
                    "scalp_signal": "HOLD", "swing_signal": "HOLD", "score": 61,
                    "price": 50.0, "atr": 0.5,
                },
            }

        def fetch_strategy_data(self):
            return self.payload

    class Runtime:
        def __init__(self):
            self.last_entry_diagnostics = {}

    legacy = Legacy()
    runtime = Runtime()
    candles_15m = {symbol: [_candle(100 + i) for i in range(12)] for symbol in legacy.latest_scores}
    candles_5m = {symbol: [_candle(100 + i) for i in range(12)] for symbol in legacy.latest_scores}
    mtf = {
        "TESTUSDT": {"1h": [_candle(200 + i) for i in range(12)], "4h": [_candle(300 + i) for i in range(12)]},
        "HOLDUSDT": {"1h": [_candle(400 + i) for i in range(12)], "4h": [_candle(500 + i) for i in range(12)]},
    }
    legacy.payload = (
        {"TESTUSDT": {"lastPrice": "100.0", "bidPrice": "99.99", "askPrice": "100.01"},
         "HOLDUSDT": {"lastPrice": "50.0", "bidPrice": "49.99", "askPrice": "50.01"}},
        candles_15m, candles_5m,
    )

    bridge = install(legacy=legacy, runtime=runtime, mtf_candles=mtf, trading_symbols=["TESTUSDT", "HOLDUSDT"])
    assert legacy.fetch_strategy_data() is legacy.payload
    summary = bridge.capture_cycle()

    assert summary["evaluated_symbols"] == 2
    assert summary["legacy_buy_candidates"] == 1
    assert summary["captured_candidates"] == 1
    assert set(bridge.latest_captures()) == {"TESTUSDT"}

    capture = bridge.latest_captures()["TESTUSDT"]
    assert capture["legacy_result"]["score"] == 72
    assert capture["entry_scenario"]["risk"]["reward_risk"] is None
    assert capture["entry_scenario"]["risk"]["target_status"] == "NO_TARGET_ABOVE_ENTRY"
    assert len(capture["closed_candle_windows"]["5m"]) == 8
    assert len(capture["closed_candle_windows"]["15m"]) == 8
    assert len(capture["closed_candle_windows"]["1h"]) == 8
    assert len(capture["closed_candle_windows"]["4h"]) == 8
    assert runtime.last_entry_diagnostics["TESTUSDT"]["entry_v2_shadow"]["legacy_score"] == 72
    assert "HOLDUSDT" not in runtime.last_entry_diagnostics


def test_runtime_capture_keeps_reward_risk_unknown_instead_of_borrowing_old_formula():
    class Legacy:
        latest_scores = {
            "TESTUSDT": {
                "signal": "BUY", "trade_mode": "SCALP", "scalp_signal": "BUY", "swing_signal": "HOLD",
                "score": 70, "scalp_score": 70, "swing_score": 45, "price": 100.0, "atr": 1.5,
                "scalp_reasons": ["15M_BOLLINGER_NEAR_SUPPORT"], "scalp_confirmed_reversal": False,
                "scalp_recovery_confirmation": True, "volume_ratio_5m": 1.1,
            }
        }
        def fetch_strategy_data(self):
            return (
                {"TESTUSDT": {"lastPrice": "100", "bidPrice": "99.99", "askPrice": "100.01"}},
                {"TESTUSDT": [_candle(100 + i) for i in range(12)]},
                {"TESTUSDT": [_candle(100 + i) for i in range(12)]},
            )

    class Runtime:
        last_entry_diagnostics = {}

    bridge = install(
        legacy=Legacy(), runtime=Runtime(),
        mtf_candles={"TESTUSDT": {"1h": [_candle(200 + i) for i in range(12)], "4h": [_candle(300 + i) for i in range(12)]}},
        trading_symbols=["TESTUSDT"],
    )
    bridge.legacy.fetch_strategy_data(); bridge.capture_cycle()
    capture = bridge.latest_captures()["TESTUSDT"]
    assert capture["entry_scenario"]["risk"]["stop_distance_percent"] > 0
    assert capture["entry_scenario"]["risk"]["reward_risk"] is None
    assert capture["entry_scenario"]["risk"]["target_status"] == "NO_TARGET_ABOVE_ENTRY"
    assert capture["v2_decision"]["failed_gate"] in {
        "SELLER_PRESSURE_NOT_INVALIDATED", "STRUCTURAL_RECLAIM_NOT_CONFIRMED", "REWARD_RISK_PENDING", "VOLUME_NOT_CONFIRMING", "NO_TARGET_ABOVE_ENTRY",
    }


def test_runtime_capture_calculates_real_structure_target_without_changing_legacy():
    class Legacy:
        latest_scores = {
            "TESTUSDT": {
                "signal": "BUY", "trade_mode": "SCALP", "scalp_signal": "BUY", "swing_signal": "HOLD",
                "score": 70, "scalp_score": 70, "swing_score": 45, "price": 100.0, "atr": 1.0,
                "scalp_reasons": ["15M_BOLLINGER_NEAR_SUPPORT"], "scalp_confirmed_reversal": True,
                "scalp_recovery_confirmation": False, "volume_ratio_5m": 1.2,
            }
        }
        def fetch_strategy_data(self):
            candles = [
                {"open": 100, "high": 100.5, "low": 99.5, "close": 100.2, "volume": 100.0},
                {"open": 100.2, "high": 102.0, "low": 99.8, "close": 101.0, "volume": 100.0},
                {"open": 101.0, "high": 101.5, "low": 100.0, "close": 100.6, "volume": 100.0},
                {"open": 100.6, "high": 105.0, "low": 100.2, "close": 104.0, "volume": 100.0},
                {"open": 104.0, "high": 104.5, "low": 103.5, "close": 100.5, "volume": 100.0},
                {"open": 100.5, "high": 101.0, "low": 99.8, "close": 100.0, "volume": 100.0},
            ]
            return (
                {"TESTUSDT": {"lastPrice": "100", "bidPrice": "99.99", "askPrice": "100.01"}},
                {"TESTUSDT": candles}, {"TESTUSDT": candles},
            )

    class Runtime:
        last_entry_diagnostics = {}

    legacy = Legacy(); original = {"signal": "BUY", "trade_mode": "SCALP", "score": 70}
    bridge = install(legacy=legacy, runtime=Runtime(), mtf_candles={"TESTUSDT": {"1h": [], "4h": []}}, trading_symbols=["TESTUSDT"])
    bridge.legacy.fetch_strategy_data(); bridge.capture_cycle()
    capture = bridge.latest_captures()["TESTUSDT"]
    assert capture["entry_scenario"]["risk"]["target_price"] == 102.0
    assert capture["entry_scenario"]["risk"]["target_source"] == "5m_PIVOT_HIGH"
    assert capture["entry_scenario"]["risk"]["reward_risk"] == 1.0
    assert capture["entry_scenario"]["risk"]["target_status"] == "VALID"
    assert capture["legacy_result"]["signal"] == original["signal"]

def test_runtime_capture_separates_dual_lane_candidates_and_position_identity():
    class Legacy:
        latest_scores = {
            "DUALUSDT": {
                "symbol": "DUALUSDT",
                "signal": "BUY",
                "trade_mode": "SWING",
                "scalp_signal": "BUY",
                "swing_signal": "BUY",
                "score": 86,
                "scalp_score": 72,
                "swing_score": 86,
                "price": 100.0,
                "atr": 1.0,
                "scalp_confirmed_reversal": True,
                "scalp_recovery_confirmation": True,
                "volume_ratio_5m": 1.3,
            }
        }

        def fetch_strategy_data(self):
            candles = {"DUALUSDT": [_candle(100 + i) for i in range(12)]}
            return (
                {"DUALUSDT": {"lastPrice": "100", "bidPrice": "99.99", "askPrice": "100.01"}},
                candles,
                candles,
            )

        def score_symbol(self, symbol, *args, **kwargs):
            return self.latest_scores[symbol]

    class Repository:
        def __init__(self):
            self.positions = []

        def add(self, position):
            self.positions.append(position)

    class Runtime:
        def __init__(self):
            self.last_entry_diagnostics = {}
            self.repository = Repository()

    legacy = Legacy()
    runtime = Runtime()
    bridge = install(
        legacy=legacy,
        runtime=runtime,
        mtf_candles={
            "DUALUSDT": {
                "1h": [_candle(200 + i) for i in range(12)],
                "4h": [_candle(300 + i) for i in range(12)],
            }
        },
        trading_symbols=["DUALUSDT"],
    )

    legacy.fetch_strategy_data()
    legacy.score_symbol("DUALUSDT", None, None)

    by_mode = bridge.latest_captures_by_mode()
    assert set(by_mode) == {"DUALUSDT|SCALP", "DUALUSDT|SWING"}

    scalp = by_mode["DUALUSDT|SCALP"]
    swing = by_mode["DUALUSDT|SWING"]
    assert scalp["legacy_result"]["trade_mode"] == "SCALP"
    assert scalp["legacy_result"]["score"] == 72
    assert swing["legacy_result"]["trade_mode"] == "SWING"
    assert swing["legacy_result"]["score"] == 86
    assert scalp["capture_id"] != swing["capture_id"]

    diagnostics = runtime.last_entry_diagnostics["DUALUSDT"]["entry_v2_shadow_by_mode"]
    assert diagnostics["SCALP"]["capture_id"] == scalp["capture_id"]
    assert diagnostics["SWING"]["capture_id"] == swing["capture_id"]

    class Position:
        def __init__(self, mode):
            self.symbol = "DUALUSDT"
            self.entry_metadata = {"trade_mode": mode}

    scalp_position = Position("SCALP")
    swing_position = Position("SWING")
    runtime.repository.add(scalp_position)
    runtime.repository.add(swing_position)

    assert scalp_position.entry_metadata["entry_v2_shadow_capture_id"] == scalp["capture_id"]
    assert swing_position.entry_metadata["entry_v2_shadow_capture_id"] == swing["capture_id"]
\n