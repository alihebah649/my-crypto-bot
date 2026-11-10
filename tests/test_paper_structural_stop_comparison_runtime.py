from datetime import datetime, timezone

from core.paper_structural_stop_comparison_runtime import (
    PaperStructuralStopComparisonCoordinator,
)


class FakeStore:
    def __init__(self):
        self.rows = {}
        self.last_error = None

    def append(self, row):
        key = row["capture_id"]
        if key in self.rows:
            return False
        self.rows[key] = dict(row)
        return True

    def upsert(self, row):
        self.rows[row["capture_id"]] = dict(row)
        return True

    def read_all(self):
        self.last_error = None
        return [dict(row) for row in self.rows.values()]


class FakeRepository:
    def __init__(self, position):
        self.position = position

    def get(self, position_id):
        if self.position["position_id"] != position_id:
            return None
        return self.position


class FakeStream:
    def __init__(self, candles):
        self.candles = candles
        self.calls = []

    def get_kline_history(self, symbol, interval, limit):
        self.calls.append((symbol, interval, limit))
        return list(self.candles)


class FakeRuntime:
    def __init__(self, fee_rate=0.001):
        self.execution_adapter = type("Adapter", (), {"fee_rate": fee_rate})()


def capture(capture_id, venue):
    return {
        "capture_id": capture_id,
        "captured_at": "2026-11-08T08:00:30+00:00",
        "symbol": "OPUSDT",
        "legacy_result": {"price": 100.0, "trade_mode": "SCALP"},
        "entry_scenario": {
            "trade_mode": "SCALP",
            "risk": {
                "atr_stop_loss": 98.0,
                "structural_stop_candidate": 97.0,
                "target_price": 104.0,
                "target_source": "PIVOT_HIGH",
                "target_status": "VALID",
                "reward_risk": 2.0,
            },
        },
        "venue": venue,
    }


def position(position_id, venue, *, status="OPEN"):
    return {
        "position_id": position_id,
        "symbol": "OPUSDT",
        "entry_price": 100.0,
        "stop_loss": 98.0,
        "status": status,
        "current_price": 100.0,
        "realized_pnl": 0.0,
        "total_fees": 0.0,
        "entry_metadata": {
            "trade_mode": "SCALP",
            "entry_v2_capture_id": f"capture-{venue.lower()}",
        },
        "exit_metadata": {},
    }


def bar(open_time, *, high, low, close, closed=True):
    return {
        "open_time": open_time,
        "close_time": open_time + 299999,
        "high": high,
        "low": low,
        "close": close,
        "is_closed": closed,
    }


def first_bar_open():
    ts = datetime.fromisoformat("2026-11-08T08:00:30+00:00").timestamp()
    return (int(ts * 1000) // 300000 + 1) * 300000


def test_hosts_independent_venue_contexts_and_never_cross_uses_candles():
    coordinator = PaperStructuralStopComparisonCoordinator()
    bybit_position = position("BYBIT-1", "BYBIT")
    okx_position = position("OKX-1", "OKX")
    bybit_stream = FakeStream([
        bar(first_bar_open(), high=101.0, low=99.0, close=100.5)
    ])
    okx_stream = FakeStream([
        bar(first_bar_open(), high=105.0, low=99.0, close=104.5)
    ])
    bybit_store, okx_store = FakeStore(), FakeStore()

    coordinator.add_context(
        context_key="BYBIT",
        venue="BYBIT",
        venue_mode="BYBIT_HOSTED_PAPER_LAB",
        repository=FakeRepository(bybit_position),
        stream=bybit_stream,
        runtime=FakeRuntime(),
        evidence_store=bybit_store,
    )
    coordinator.add_context(
        context_key="OKX",
        venue="OKX",
        venue_mode="OKX_HOSTED_PAPER_LAB",
        repository=FakeRepository(okx_position),
        stream=okx_stream,
        runtime=FakeRuntime(),
        evidence_store=okx_store,
    )
    coordinator.register_start("BYBIT", bybit_position, capture("capture-bybit", "BYBIT"))
    coordinator.register_start("OKX", okx_position, capture("capture-okx", "OKX"))

    coordinator.advance()

    assert bybit_stream.calls == [("OPUSDT", "5m", 60)]
    assert okx_stream.calls == [("OPUSDT", "5m", 60)]
    assert bybit_store.rows["BYBIT-1:START"]["venue"] == "BYBIT"
    assert okx_store.rows["OKX-1:START"]["venue"] == "OKX"
    assert bybit_store.rows["BYBIT-1:START"]["bars_observed"] == 1
    assert okx_store.rows["OKX-1:START"]["bars_observed"] == 1


def test_completed_pair_waits_for_real_position_close_then_writes_one_final():
    coordinator = PaperStructuralStopComparisonCoordinator()
    opened = position("BYBIT-2", "BYBIT")
    repository = FakeRepository(opened)
    store = FakeStore()
    stream = FakeStream([
        bar(first_bar_open(), high=104.5, low=99.0, close=104.0)
    ])
    coordinator.add_context(
        context_key="BYBIT",
        venue="BYBIT",
        venue_mode="BYBIT_HOSTED_PAPER_LAB",
        repository=repository,
        stream=stream,
        runtime=FakeRuntime(),
        evidence_store=store,
    )
    coordinator.register_start("BYBIT", opened, capture("capture-bybit", "BYBIT"))

    coordinator.advance()
    report_snapshot = coordinator.snapshot()
    assert report_snapshot["active_positions"] == 1
    assert report_snapshot["shadow_paths_complete_waiting_for_actual_close"] == 1
    assert "BYBIT-2:FINAL" not in store.rows
    assert store.rows["BYBIT-2:START"]["status"] == "COMPLETE"

    opened["status"] = "CLOSED"
    opened["realized_pnl"] = 0.27
    opened["total_fees"] = 0.02
    opened["current_price"] = 103.0
    opened["exit_metadata"] = {"exit_price": 103.0, "exit_reason": "TRAILING_STOP"}
    coordinator.advance()

    final = store.rows["BYBIT-2:FINAL"]
    assert final["record_type"] == "FINAL"
    assert final["actual_paper_outcome"]["status"] == "CLOSED"
    assert final["actual_paper_outcome"]["realized_pnl"] == 0.27
    assert final["actual_paper_outcome"]["total_fees"] == 0.02
    assert final["venue"] == "BYBIT"
    assert coordinator.snapshot()["active_positions"] == 0


def test_restore_resumes_each_context_only_from_its_own_start_record():
    coordinator = PaperStructuralStopComparisonCoordinator()
    opened = position("OKX-RESTORED", "OKX")
    store = FakeStore()
    start = {
        **__import__("core.paper_structural_stop_comparison").paper_structural_stop_comparison
        .build_structural_stop_comparison_watch(
            capture("capture-okx", "OKX"),
            opened,
            fee_rate=0.001,
            venue="OKX",
            venue_mode="OKX_HOSTED_PAPER_LAB",
        ),
        "status": "COMPLETE",
    }
    store.append(start)
    store.append({
        "trial_name": start["trial_name"],
        "record_type": "FINAL",
        "record_id": "ALREADY-FINAL",
        "capture_id": "ALREADY-FINAL",
        "position_id": "ALREADY-FINAL",
        "venue": "OKX",
    })

    result = coordinator.add_context(
        context_key="OKX",
        venue="OKX",
        venue_mode="OKX_HOSTED_PAPER_LAB",
        repository=FakeRepository(opened),
        stream=FakeStream([]),
        runtime=FakeRuntime(),
        evidence_store=store,
    )

    assert result["restored_active_positions"] == 1
    assert coordinator.snapshot()["contexts"]["OKX"]["active_positions"] == 1


def test_unmeasurable_capture_creates_decision_and_no_active_watch():
    coordinator = PaperStructuralStopComparisonCoordinator()
    opened = position("BYBIT-SKIP", "BYBIT")
    store = FakeStore()
    coordinator.add_context(
        context_key="BYBIT",
        venue="BYBIT",
        venue_mode="BYBIT_HOSTED_PAPER_LAB",
        repository=FakeRepository(opened),
        stream=FakeStream([]),
        runtime=FakeRuntime(),
        evidence_store=store,
    )
    bad = capture("capture-bybit", "BYBIT")
    bad["entry_scenario"]["risk"]["structural_stop_candidate"] = None

    assert coordinator.register_start("BYBIT", opened, bad) is False
    decision = store.rows["BYBIT-SKIP:DECISION"]
    assert decision["record_type"] == "DECISION"
    assert decision["reason"] == "STRUCTURAL_STOP_CANDIDATE_UNAVAILABLE"
    assert coordinator.snapshot()["active_positions"] == 0
