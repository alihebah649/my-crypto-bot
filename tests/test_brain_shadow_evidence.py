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


def test_entry_cycle_brain_shadow_binds_to_matching_position_lane():
    from core.brain_shadow_binding import attach_brain_shadow_entry

    class FakeRepository:
        def __init__(self):
            self.positions = []
            self.updated = []

        def get_open_positions(self):
            return list(self.positions)

        def update(self, position):
            self.updated.append(position.position_id)

    repo = FakeRepository()
    scalp = FakePosition("POS-SCALP", "TESTUSDT", "SCALP", "cap-1", status="OPEN")
    swing = FakePosition("POS-SWING", "TESTUSDT", "SWING", "cap-2", status="OPEN")
    repo.positions.extend([scalp, swing])

    record = {
        "capture_id": "cap-1",
        "trade_mode": "SCALP",
        "brain_action": "BUY",
        "brain_confidence": 70.0,
        "brain_reason": "SCALP_RECOVERY_CONFIRMED",
        "agreement": True,
        "timestamp": 1234.5,
    }

    assert attach_brain_shadow_entry(repo, record) == "POS-SCALP"
    assert scalp.entry_metadata["brain_shadow_entry"] == record
    assert swing.entry_metadata.get("brain_shadow_entry") is None
    assert repo.updated == ["POS-SCALP"]


def test_paper_outcome_reads_position_bound_brain_shadow_without_store_lookup():
    from core.paper_outcome_evidence import build_paper_outcome_evidence

    position = FakePosition(
        "POS-BOUND", "TESTUSDT", "SCALP", "cap-bound", status="CLOSED", pnl=0.25, fees=0.1
    )
    position.opened_at = 100.0
    position.closed_at = 130.0
    position.quantity = 1.0
    position.entry_price = 100.0
    position.current_price = 101.0
    position.stop_loss = 98.0
    position.take_profit = None
    position.gross_pnl = 0.35
    position.exit_metadata = {"exit_price": 101.0}
    position.entry_context = {"strategy_score": {}}
    position.entry_metadata["brain_shadow_entry"] = {
        "capture_id": "cap-bound",
        "trade_mode": "SCALP",
        "brain_action": "BUY",
        "brain_confidence": 72.0,
        "brain_reason": "CONFIRMED_ENTRY",
        "agreement": True,
    }

    record = build_paper_outcome_evidence(position)
    assert record["brain"]["capture_id"] == "cap-bound"
    assert record["brain"]["action"] == "BUY"
    assert record["brain"]["confidence"] == 72.0
    assert record["brain"]["reason"] == "CONFIRMED_ENTRY"
    assert record["brain"]["agreement"] is True
