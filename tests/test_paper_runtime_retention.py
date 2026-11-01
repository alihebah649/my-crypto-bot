from __future__ import annotations

import time
from types import SimpleNamespace

from core.paper_runtime_retention import (
    PAPER_POSITION_RETENTION_SECONDS,
    compact_paper_order_history,
    persist_or_confirm_paper_outcome,
    prune_main_paper_history,
)
from trade_manager.models import Position, PositionSide, PositionStatus
from trade_manager.repository import PositionRepository


class _EvidenceStore:
    def __init__(self, *, append_result=False, existing=None, last_error=None):
        self.append_result = append_result
        self.existing = existing
        self.last_error = last_error
        self.append_calls = 0
        self.lookup_calls = 0

    def append(self, record):
        self.append_calls += 1
        return self.append_result

    def get_by_identity(self, key):
        self.lookup_calls += 1
        return self.existing if self.existing and self.existing.get("position_id") == key else None


def _position(position_id, status, closed_at, *, telegram_sent=False):
    now = time.time()
    return Position(
        position_id=position_id,
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        status=status,
        quantity=0.01,
        entry_price=50_000.0,
        current_price=50_000.0,
        stop_loss=49_000.0,
        take_profit=52_000.0,
        opened_at=now - 60.0 * 86400.0,
        closed_at=closed_at,
        metadata={},
        entry_metadata={},
        exit_metadata={"telegram_notification_sent": telegram_sent},
    )


def test_outcome_append_success_is_durable():
    store = _EvidenceStore(append_result=True)
    assert persist_or_confirm_paper_outcome(store, {"position_id": "P-1"}) is True
    assert store.append_calls == 1
    assert store.lookup_calls == 0


def test_duplicate_append_is_confirmed_by_targeted_identity_lookup():
    store = _EvidenceStore(existing={"position_id": "P-2"})
    assert persist_or_confirm_paper_outcome(store, {"position_id": "P-2"}) is True
    assert store.append_calls == 1
    assert store.lookup_calls == 1


def test_failed_append_is_not_mistaken_for_durable_evidence():
    store = _EvidenceStore(last_error="database unavailable")
    assert persist_or_confirm_paper_outcome(store, {"position_id": "P-3"}) is False
    assert store.lookup_calls == 0


def test_duplicate_without_matching_durable_record_is_not_confirmed():
    store = _EvidenceStore(existing={"position_id": "OTHER"})
    assert persist_or_confirm_paper_outcome(store, {"position_id": "P-4"}) is False


def test_main_pruning_preserves_loss_window_unsent_and_unpersisted_positions():
    now = 2_000_000_000.0
    cutoff = now - PAPER_POSITION_RETENTION_SECONDS
    repo = PositionRepository()
    old_durable_notified = _position(
        "old-durable-notified", PositionStatus.CLOSED, cutoff - 60.0, telegram_sent=True
    )
    old_durable_unsent = _position(
        "old-durable-unsent", PositionStatus.CLOSED, cutoff - 120.0, telegram_sent=False
    )
    old_unpersisted = _position(
        "old-unpersisted", PositionStatus.CLOSED, cutoff - 180.0, telegram_sent=True
    )
    recent = _position("recent", PositionStatus.CLOSED, now - 86400.0, telegram_sent=True)
    old_cancelled = _position("cancelled", PositionStatus.CANCELLED, cutoff - 240.0)
    old_failed = _position("failed", PositionStatus.FAILED, cutoff - 300.0)
    active = _position("active", PositionStatus.OPEN, 0.0)

    for position in (
        old_durable_notified,
        old_durable_unsent,
        old_unpersisted,
        recent,
        old_cancelled,
        old_failed,
        active,
    ):
        repo.add(position)

    class _Ledger:
        def __init__(self):
            self.synced = None

        def sync(self, positions):
            self.synced = list(positions)

    ledger = _Ledger()
    runtime = SimpleNamespace(repository=repo, loss_ledger=ledger)
    logged = {
        "old-durable-notified",
        "old-durable-unsent",
        "recent",
    }

    removed = prune_main_paper_history(
        runtime,
        object(),
        logged,
        now_epoch=now,
    )

    assert set(removed) == {
        "old-durable-notified",
        "cancelled",
        "failed",
    }
    assert repo.get("old-durable-notified") is None
    assert repo.get("old-durable-unsent") is old_durable_unsent
    assert repo.get("old-unpersisted") is old_unpersisted
    assert repo.get("recent") is recent
    assert repo.get("active") is active
    assert logged == {"old-durable-unsent", "recent"}
    assert ledger.synced is not None
    assert {p.position_id for p in ledger.synced} == {
        "old-durable-unsent",
        "old-unpersisted",
        "recent",
    }


def test_main_pruning_is_disabled_without_durable_evidence_store():
    now = 2_000_000_000.0
    old = _position("old", PositionStatus.CLOSED, now - 60.0 * 86400.0, telegram_sent=True)
    repo = PositionRepository()
    repo.add(old)
    runtime = SimpleNamespace(repository=repo, loss_ledger=None)
    logged = {"old"}

    assert prune_main_paper_history(runtime, None, logged, now_epoch=now) == []
    assert repo.get("old") is old
    assert logged == {"old"}


def test_paper_order_compaction_keeps_latest_completed_and_all_unresolved():
    class _Adapter:
        pass

    adapter = _Adapter()
    adapter.orders = {
        f"order-{i}": SimpleNamespace(status=SimpleNamespace(value="FILLED"))
        for i in range(1003)
    }
    adapter.orders["old-pending"] = SimpleNamespace(
        status=SimpleNamespace(value="PENDING")
    )

    removed = compact_paper_order_history(adapter, keep=1000)

    assert removed == 3
    assert len(adapter.orders) == 1001
    assert "old-pending" in adapter.orders
    assert "order-0" not in adapter.orders
    assert "order-2" not in adapter.orders
    assert "order-3" in adapter.orders
    assert "order-1002" in adapter.orders


def test_paper_order_compaction_is_noop_under_limit():
    class _Adapter:
        orders = {"one": object()}

    assert compact_paper_order_history(_Adapter(), keep=1000) == 0
