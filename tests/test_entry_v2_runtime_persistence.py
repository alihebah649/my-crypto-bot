from __future__ import annotations

import sys

from engine.entry_v2_runtime_capture import install


def _candle(value: float) -> dict:
    return {
        "open": value,
        "high": value + 0.5,
        "low": value - 0.5,
        "close": value + 0.2,
        "volume": 100.0,
    }


def _legacy():
    class Legacy:
        latest_scores = {
            "TESTUSDT": {
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
                "scalp_confirmed_reversal": False,
                "scalp_recovery_confirmation": True,
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

    return Legacy()


class Runtime:
    def __init__(self, persistence_dir):
        self.persistence_dir = str(persistence_dir)
        self.last_entry_diagnostics = {}


def test_runtime_capture_auto_creates_durable_store(tmp_path):
    legacy = _legacy()
    runtime = Runtime(tmp_path)
    bridge = install(
        legacy=legacy,
        runtime=runtime,
        mtf_candles={"TESTUSDT": {"1h": [], "4h": []}},
        trading_symbols=["TESTUSDT"],
    )

    assert bridge.capture_store is not None
    bridge.legacy.fetch_strategy_data()
    summary = bridge.capture_cycle()

    path = tmp_path / "entry_v2_shadow" / "captures.jsonl"
    assert path.exists()
    assert summary["persisted_records"] == 1
    assert summary["persistent_total_records"] == 1

    rebuilt = type(bridge.capture_store)(path)
    assert rebuilt.count() == 1
    assert rebuilt.recent(1)[0]["symbol"] == "TESTUSDT"


def test_runtime_capture_reads_live_main_mtf_snapshot_when_reference_is_rebound(tmp_path, monkeypatch):
    legacy = _legacy()
    runtime = Runtime(tmp_path)
    live_mtf = {
        "TESTUSDT": {
            "1h": [_candle(200 + i) for i in range(12)],
            "4h": [_candle(300 + i) for i in range(12)],
        }
    }
    main_module = sys.modules["__main__"]
    monkeypatch.setattr(main_module, "_mtf_candles", live_mtf, raising=False)

    bridge = install(
        legacy=legacy,
        runtime=runtime,
        mtf_candles={},
        trading_symbols=["TESTUSDT"],
    )
    bridge.legacy.fetch_strategy_data()
    bridge.capture_cycle()

    capture = bridge.latest_captures()["TESTUSDT"]
    assert len(capture["closed_candle_windows"]["1h"]) == 8
    assert len(capture["closed_candle_windows"]["4h"]) == 8
    assert len(capture["entry_scenario"]["structure"]["multi_candle_by_timeframe"]["1h"]["patterns"]) >= 0
