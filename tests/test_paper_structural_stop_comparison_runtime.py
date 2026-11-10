from datetime import datetime, timezone

from core.paper_structural_stop_comparison import build_structural_stop_comparison_watch
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

    def get_open_positions(self):
        if self.position.get("status") in {"OPEN", "HOLD", "REVIEW_REQUIRED", "PARTIALLY_CLOSED"}:
            return [self.position]
        return []


class FakeStream:
    def __init__(self, candles):
        self.candles = candles
        self.calls = []

    def get_kline_history(self, symbol, interval, limit):
        self.calls.append((symbol, interval, limit))
        return list(self.candles)


class FakeCaptureStore:
    def __init__(self, records=None, *, fail_once=False):
        self.records = dict(records or {})
        self.last_error = None
        self.fail_once = fail_once

    def get_by_identity(self, identity):
        if self.fail_once:
            self.fail_once = False
            self.last_error = "ConnectionError: temporary database interruption"
            return None
        self.last_error = None
        row = self.records.get(identity)
        return dict(row) if row is not None else None


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
        **build_structural_stop_comparison_watch(
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


def test_existing_open_position_is_seeded_only_with_exact_capture_and_entry_bar_coverage():
    coordinator = PaperStructuralStopComparisonCoordinator()
    opened = position("BYBIT-BACKFILL", "BYBIT")
    capture_row = capture("capture-bybit", "BYBIT")
    entry_bar_open = first_bar_open() - 300000
    stream = FakeStream([
        bar(entry_bar_open, high=101.0, low=99.0, close=100.0),
        bar(first_bar_open(), high=101.2, low=99.2, close=100.5),
    ])
    store = FakeStore()
    coordinator.add_context(
        context_key="BYBIT",
        venue="BYBIT",
        venue_mode="BYBIT_HOSTED_PAPER_LAB",
        repository=FakeRepository(opened),
        stream=stream,
        runtime=FakeRuntime(),
        evidence_store=store,
        entry_capture_store=FakeCaptureStore({capture_row["capture_id"]: capture_row}),
    )

    seeded = coordinator.seed_existing_open_positions("BYBIT")

    assert seeded["existing_open_positions_seen"] == 1
    assert seeded["started"] == 1
    assert seeded["skipped"] == 0
    start = store.rows["BYBIT-BACKFILL:START"]
    assert start["source_capture_id"] == "capture-bybit"
    assert start["atr_stop_source"] == "ENTRY_V2_CAPTURE_ATR_STOP"
    assert start["venue"] == "BYBIT"

    coordinator.advance()
    assert store.rows["BYBIT-BACKFILL:START"]["bars_observed"] == 1


def test_existing_open_position_is_skipped_when_5m_history_does_not_cover_entry():
    coordinator = PaperStructuralStopComparisonCoordinator()
    opened = position("BYBIT-OLD", "BYBIT")
    capture_row = capture("capture-bybit", "BYBIT")
    stream = FakeStream([
        bar(first_bar_open() + 300000, high=101.0, low=99.0, close=100.0)
    ])
    store = FakeStore()
    coordinator.add_context(
        context_key="BYBIT",
        venue="BYBIT",
        venue_mode="BYBIT_HOSTED_PAPER_LAB",
        repository=FakeRepository(opened),
        stream=stream,
        runtime=FakeRuntime(),
        evidence_store=store,
        entry_capture_store=FakeCaptureStore({capture_row["capture_id"]: capture_row}),
    )

    seeded = coordinator.seed_existing_open_positions("BYBIT")

    assert seeded["started"] == 0
    assert seeded["skipped"] == 1
    assert seeded["skip_reasons"]["HISTORICAL_5M_BUFFER_DOES_NOT_COVER_ENTRY"] == 1
    decision = store.rows["BYBIT-OLD:DECISION"]
    assert decision["reason"] == "HISTORICAL_5M_BUFFER_DOES_NOT_COVER_ENTRY"
    assert coordinator.snapshot()["active_positions"] == 0


def test_existing_open_position_is_skipped_when_exact_entry_capture_is_missing():
    coordinator = PaperStructuralStopComparisonCoordinator()
    opened = position("OKX-NO-CAPTURE", "OKX")
    store = FakeStore()
    coordinator.add_context(
        context_key="OKX",
        venue="OKX",
        venue_mode="OKX_HOSTED_PAPER_LAB",
        repository=FakeRepository(opened),
        stream=FakeStream([]),
        runtime=FakeRuntime(),
        evidence_store=store,
        entry_capture_store=FakeCaptureStore(),
    )

    seeded = coordinator.seed_existing_open_positions("OKX")

    assert seeded["started"] == 0
    assert seeded["skipped"] == 1
    assert seeded["skip_reasons"]["EXACT_ENTRY_V2_CAPTURE_NOT_FOUND"] == 1
    decision = store.rows["OKX-NO-CAPTURE:DECISION"]
    assert decision["source_capture_id"] == "capture-okx"
    assert decision["reason"] == "EXACT_ENTRY_V2_CAPTURE_NOT_FOUND"


def test_existing_position_backfill_retries_temporary_capture_store_failure():
    coordinator = PaperStructuralStopComparisonCoordinator()
    opened = position("BYBIT-RETRY", "BYBIT")
    capture_row = capture("capture-bybit", "BYBIT")
    store = FakeStore()
    capture_store = FakeCaptureStore(
        {capture_row["capture_id"]: capture_row},
        fail_once=True,
    )
    stream = FakeStream([
        bar(first_bar_open() - 300000, high=101.0, low=99.0, close=100.0),
        bar(first_bar_open(), high=101.2, low=99.2, close=100.5),
    ])
    coordinator.add_context(
        context_key="BYBIT",
        venue="BYBIT",
        venue_mode="BYBIT_HOSTED_PAPER_LAB",
        repository=FakeRepository(opened),
        stream=stream,
        runtime=FakeRuntime(),
        evidence_store=store,
        entry_capture_store=capture_store,
    )

    first_attempt = coordinator.seed_existing_open_positions("BYBIT")
    assert first_attempt["retry_required"] is True
    assert first_attempt["skipped"] == 0
    assert "BYBIT-RETRY:DECISION" not in store.rows

    second_attempt = coordinator.seed_existing_open_positions("BYBIT")
    assert second_attempt["retry_required"] is False
    assert second_attempt["started"] == 1
    assert "BYBIT-RETRY:START" in store.rows
