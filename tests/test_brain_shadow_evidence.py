from core.brain_shadow_runtime import BrainShadowRuntime
from core.brain_shadow_capture_store import BrainShadowCaptureStore
from core.brain_shadow_outcome_analysis import analyze_brain_shadow_outcomes


class FakeStatus:
    def __init__(self, name):
        self.name = name


class FakePosition:
    def __init__(self, position_id, symbol, lane, capture_id, status="CLOSED", pnl=0.0, fees=0.0):
        self.position_id = position_id
        self.symbol = symbol
        self.status = FakeStatus(status)
        self.entry_metadata = {
            "trade_mode": lane,
            "entry_v2_shadow_capture_id": capture_id,
        }
        self.realized_pnl = pnl
        self.total_fees = fees


def test_brain_shadow_record_preserves_entry_capture_identity():
    runtime = BrainShadowRuntime()
    strategy = {
        "signal": "BUY",
        "score": 70,
        "trade_mode": "SCALP",
        "scalp_score": 70,
        "scalp_confirmed_reversal": True,
        "scalp_recovery_confirmation": True,
        "volume_ratio_5m": 1.4,
    }
    result = runtime.evaluate_entry("BTCUSDT", strategy, entry_v2_capture_id="cap-123")
    payload = result.to_dict()
    assert payload["capture_id"] == "cap-123"


def test_brain_shadow_outcomes_segment_market_and_lane():
    record = {
        "capture_id": "cap-1",
        "trade_mode": "SCALP",
        "symbol": "TESTUSDT",
        "strategy_action": "BUY",
        "strategy_score": 70.0,
        "brain_action": "HOLD",
        "brain_reason": "BEAR_VOLUME_NOT_CONFIRMING",
        "context": {
            "market_regime": "BEAR",
            "symbol_regime": "BEAR",
            "trade_mode": "SCALP",
        },
    }
    position = FakePosition(
        "POS-1", "TESTUSDT", "SCALP", "cap-1", pnl=-0.5, fees=0.1
    )
    report = analyze_brain_shadow_outcomes([record], [position])
    assert report["coverage"]["matched_positions"] == 1
    assert report["by_market_regime"]["BEAR"]["losses"] == 1
    assert report["by_lane_market_regime"]["SCALP|BEAR"]["losses"] == 1
    assert report["legacy_executed_brain_rejected"]["losses"] == 1


def test_brain_shadow_store_round_trip(tmp_path):
    store = BrainShadowCaptureStore(tmp_path / "brain.jsonl")
    assert store.append({"capture_id": "cap-1", "brain_action": "HOLD"}) is True
    assert store.read_all() == [{"capture_id": "cap-1", "brain_action": "HOLD"}]
