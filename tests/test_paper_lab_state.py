from __future__ import annotations

import json
import time

import pytest

from core.paper_execution_adapter import PaperExecutionAdapter
from core.paper_lab_state import PostgresPaperLabState
from trade_manager.models import Position, PositionSide, PositionStatus
from trade_manager.repository import PositionRepository


class FakeResult:
    def __init__(self, rowcount=0, rows=None):
        self.rowcount = rowcount
        self.rows = list(rows or [])

    def fetchall(self):
        return list(self.rows)

    def fetchone(self):
        return self.rows[0] if self.rows else None


class FakeDatabase:
    def __init__(self):
        self.rows = {}
        self.fail_select = False


class FakeConnection:
    closed = False

    def __init__(self, db):
        self.db = db

    def execute(self, sql, params=()):
        normalized = " ".join(str(sql).split()).upper()
        if normalized.startswith("CREATE TABLE") or normalized.startswith("CREATE INDEX"):
            return FakeResult()
        if normalized.startswith("INSERT INTO PAPER_EVIDENCE"):
            evidence_type, identity_key, payload = params
            key = (evidence_type, identity_key)
            if key in self.db.rows and "DO UPDATE" not in normalized:
                return FakeResult(rowcount=0)
            self.db.rows[key] = json.loads(payload)
            return FakeResult(rowcount=1)
        if normalized.startswith("SELECT PAYLOAD"):
            if self.db.fail_select:
                raise OSError("database read unavailable")
            evidence_type = params[0]
            return FakeResult(rows=[
                (payload,)
                for (kind, _), payload in self.db.rows.items()
                if kind == evidence_type
            ])
        if normalized.startswith("SELECT COUNT(*)"):
            evidence_type = params[0]
            return FakeResult(rows=[(
                sum(1 for kind, _ in self.db.rows if kind == evidence_type),
            )])
        if normalized.startswith("DELETE FROM PAPER_EVIDENCE"):
            return FakeResult()
        raise AssertionError(f"Unhandled SQL: {normalized}")

    def commit(self):
        return None

    def close(self):
        self.closed = True


def _position(position_id: str, symbol: str, price: float) -> Position:
    return Position(
        position_id=position_id,
        symbol=symbol,
        side=PositionSide.LONG,
        status=PositionStatus.OPEN,
        quantity=0.25,
        entry_price=price,
        current_price=price,
        stop_loss=price * 0.98,
        take_profit=price * 1.04,
        entry_metadata={"venue_mode": "ISOLATED_VENUE_LAB"},
        metadata={"trade_mode": "SCALP"},
    )


def test_paper_lab_state_roundtrip_restores_cash_assets_and_open_positions():
    db = FakeDatabase()

    def connect(_url):
        return FakeConnection(db)

    first_state = PostgresPaperLabState(
        "postgres://test", venue="BYBIT", connect_factory=connect
    )
    first_adapter = PaperExecutionAdapter(initial_cash=1000.0, fee_rate=0.001)
    first_adapter.balance.cash = 875.0
    first_adapter.balance.assets = {"BTCUSDT": 0.01}
    first_adapter.set_market_price("BTCUSDT", 50_000.0)

    first_repository = PositionRepository()
    first_repository.add(_position("bybit-position-1", "BTCUSDT", 50_000.0))

    assert first_state.save(first_adapter, first_repository) is True
    assert first_state.save(first_adapter, first_repository) is False

    restored_state = PostgresPaperLabState(
        "postgres://test", venue="BYBIT", connect_factory=connect
    )
    restored_adapter = PaperExecutionAdapter(initial_cash=1000.0, fee_rate=0.001)
    restored_repository = PositionRepository()

    assert restored_state.load_into(restored_adapter, restored_repository) is True
    assert restored_adapter.balance.cash == pytest.approx(875.0)
    assert restored_adapter.balance.assets == {"BTCUSDT": pytest.approx(0.01)}
    # Live prices intentionally are not restored; WebSocket must refresh them.
    assert restored_adapter.market_prices == {}
    restored = restored_repository.get("bybit-position-1")
    assert restored is not None
    assert restored.status is PositionStatus.OPEN
    assert restored.entry_metadata["venue_mode"] == "ISOLATED_VENUE_LAB"


def test_each_venue_uses_an_independent_paper_state_namespace():
    db = FakeDatabase()

    def connect(_url):
        return FakeConnection(db)

    states = {
        venue: PostgresPaperLabState(
            "postgres://test", venue=venue, connect_factory=connect
        )
        for venue in ("BINANCE", "BYBIT", "OKX")
    }
    for venue, state in states.items():
        adapter = PaperExecutionAdapter(initial_cash=1000.0, fee_rate=0.001)
        adapter.balance.cash = {"BINANCE": 990.0, "BYBIT": 980.0, "OKX": 970.0}[venue]
        repository = PositionRepository()
        assert state.save(adapter, repository) is True

    assert set(kind for kind, _ in db.rows) == {
        "PAPER_LAB_STATE_BINANCE",
        "PAPER_LAB_STATE_BYBIT",
        "PAPER_LAB_STATE_OKX",
    }


def test_lab_state_does_not_silently_reset_on_database_read_failure():
    db = FakeDatabase()
    db.fail_select = True

    def connect(_url):
        return FakeConnection(db)

    state = PostgresPaperLabState(
        "postgres://test", venue="OKX", connect_factory=connect
    )
    adapter = PaperExecutionAdapter(initial_cash=1000.0, fee_rate=0.001)
    repository = PositionRepository()

    with pytest.raises(RuntimeError, match="Unable to read OKX Paper lab state"):
        state.load_into(adapter, repository)

    # The caller must pause/disable this lab instead of assuming it has a new
    # clean bankroll when its persisted state cannot be read.
    assert adapter.balance.cash == pytest.approx(1000.0)
    assert repository.get_open_positions() == []



def test_paper_lab_snapshot_keeps_active_and_recent_closed_risk_ledger_positions():
    db = FakeDatabase()

    def connect(_url):
        return FakeConnection(db)

    state = PostgresPaperLabState(
        "postgres://test", venue="OKX", connect_factory=connect
    )
    adapter = PaperExecutionAdapter(initial_cash=1000.0, fee_rate=0.001)
    repository = PositionRepository()

    old_closed = _position("old-closed", "BTCUSDT", 50_000.0)
    old_closed.status = PositionStatus.CLOSED
    old_closed.closed_at = time.time() - 50.0 * 24.0 * 60.0 * 60.0
    old_closed.realized_pnl = -0.5

    recent_closed = _position("recent-closed", "ETHUSDT", 2_500.0)
    recent_closed.status = PositionStatus.CLOSED
    recent_closed.closed_at = time.time() - 3.0 * 24.0 * 60.0 * 60.0
    recent_closed.realized_pnl = -0.25

    active = _position("active-position", "SOLUSDT", 100.0)
    failed = _position("failed-position", "XRPUSDT", 0.5)
    failed.status = PositionStatus.FAILED
    cancelled = _position("cancelled-position", "ADAUSDT", 0.5)
    cancelled.status = PositionStatus.CANCELLED
    repository.add(old_closed)
    repository.add(recent_closed)
    repository.add(active)
    repository.add(failed)
    repository.add(cancelled)

    assert state.save(adapter, repository) is True
    snapshot = next(
        payload
        for (kind, _identity), payload in db.rows.items()
        if kind == "PAPER_LAB_STATE_OKX"
    )
    saved_ids = {
        item["position_id"]
        for item in snapshot["positions"]["positions"]
    }
    assert saved_ids == {"recent-closed", "active-position"}

    restored = PositionRepository()
    restored.restore_snapshot(snapshot["positions"])
    assert restored.get("old-closed") is None
    assert restored.get("recent-closed").status is PositionStatus.CLOSED
    assert restored.get("active-position").status is PositionStatus.OPEN
