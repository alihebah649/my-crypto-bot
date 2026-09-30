from __future__ import annotations

import json

from core.postgres_evidence_store import PostgresEvidenceStore


class _FakeResult:
    def __init__(self, rowcount: int = 0, rows=None):
        self.rowcount = rowcount
        self._rows = list(rows or [])

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class _FakeDatabase:
    def __init__(self):
        self.rows = {}
        self.schema_created = False


class _FakeConnection:
    closed = False

    def __init__(self, db: _FakeDatabase):
        self.db = db

    def execute(self, sql, params=()):
        normalized = " ".join(str(sql).split()).upper()
        if normalized.startswith("CREATE TABLE"):
            self.db.schema_created = True
            return _FakeResult()
        if normalized.startswith("CREATE INDEX"):
            return _FakeResult()
        if normalized.startswith("INSERT INTO PAPER_EVIDENCE"):
            evidence_type, identity_key, payload = params
            key = (evidence_type, identity_key)
            if key in self.db.rows:
                return _FakeResult(rowcount=0)
            self.db.rows[key] = json.loads(payload)
            return _FakeResult(rowcount=1)
        if normalized.startswith("SELECT COUNT(*)"):
            evidence_type = params[0]
            count = sum(1 for key in self.db.rows if key[0] == evidence_type)
            return _FakeResult(rows=[(count,)])
        if normalized.startswith("SELECT PAYLOAD"):
            evidence_type = params[0]
            if "PAYLOAD ?" in normalized:
                field = params[1]
                start = str(params[3])
                end = str(params[5])
                rows = []
                for (kind, _), payload in self.db.rows.items():
                    if kind != evidence_type or field not in payload:
                        continue
                    value = str(payload[field])
                    if start <= value < end:
                        rows.append((payload,))
                return _FakeResult(rows=rows)
            rows = [(payload,) for (kind, _), payload in self.db.rows.items() if kind == evidence_type]
            return _FakeResult(rows=rows)
        if normalized.startswith("DELETE FROM PAPER_EVIDENCE"):
            evidence_type = params[0]
            delete_count = int(params[1])
            keys = [key for key in self.db.rows if key[0] == evidence_type][:delete_count]
            for key in keys:
                self.db.rows.pop(key, None)
            return _FakeResult()
        raise AssertionError(f"Unhandled SQL: {normalized}")

    def commit(self):
        return None

    def close(self):
        self.closed = True


def test_postgres_store_persists_across_new_store_instances_and_is_idempotent():
    db = _FakeDatabase()

    def connect(_url):
        return _FakeConnection(db)

    first = PostgresEvidenceStore(
        "postgres://secret@example.invalid/db",
        evidence_type="ENTRY_V2_CAPTURE",
        connect_factory=connect,
    )
    record = {
        "capture_id": "CAP-1",
        "symbol": "BTCUSDT",
        "adaptive_scalp_shadow": {
            "maturity_experiment": {
                "rule_version": 1,
                "shadow_only": True,
                "would_be_action": "WOULD_ALLOW",
            }
        },
    }

    assert first.append(record) is True
    assert first.append(record) is False
    assert first.summary() == {
        "backend": "postgres",
        "schema_version": 1,
        "evidence_type": "ENTRY_V2_CAPTURE",
        "record_count": 1,
        "last_error": None,
    }

    second = PostgresEvidenceStore(
        "postgres://secret@example.invalid/db",
        evidence_type="ENTRY_V2_CAPTURE",
        connect_factory=connect,
    )
    assert second.read_all() == [record]
    assert second.count() == 1


def test_postgres_store_separates_evidence_types():
    db = _FakeDatabase()

    def connect(_url):
        return _FakeConnection(db)

    captures = PostgresEvidenceStore("postgres://x", evidence_type="ENTRY_V2_CAPTURE", connect_factory=connect)
    outcomes = PostgresEvidenceStore("postgres://x", evidence_type="PAPER_OUTCOME", connect_factory=connect)

    assert captures.append({"capture_id": "CAP-1", "symbol": "ETHUSDT"}) is True
    assert outcomes.append({"position_id": "POS-1", "symbol": "ETHUSDT", "realized_pnl": -0.5}) is True

    assert captures.read_all() == [{"capture_id": "CAP-1", "symbol": "ETHUSDT"}]
    assert outcomes.read_all() == [{"position_id": "POS-1", "symbol": "ETHUSDT", "realized_pnl": -0.5}]


def test_count_does_not_load_payload_rows():
    db = _FakeDatabase()

    def connect(_url):
        return _FakeConnection(db)

    store = PostgresEvidenceStore(
        "postgres://secret@example.invalid/db",
        evidence_type="ENTRY_V2_CAPTURE",
        connect_factory=connect,
    )
    assert store.append({"capture_id": "CAP-1", "symbol": "BTCUSDT"}) is True
    assert store.append({"capture_id": "CAP-2", "symbol": "ETHUSDT"}) is True

    original_execute = _FakeConnection.execute

    def guarded_execute(self, sql, params=()):
        normalized = " ".join(str(sql).split()).upper()
        if normalized.startswith("SELECT PAYLOAD"):
            raise AssertionError("count() must not select payload rows")
        return original_execute(self, sql, params)

    _FakeConnection.execute = guarded_execute
    try:
        assert store.count() == 2
    finally:
        _FakeConnection.execute = original_execute



def test_read_time_range_returns_only_records_in_requested_window():
    db = _FakeDatabase()

    def connect(_url):
        return _FakeConnection(db)

    store = PostgresEvidenceStore(
        "postgres://secret@example.invalid/db",
        evidence_type="PAPER_OUTCOME",
        connect_factory=connect,
    )
    assert store.append({
        "position_id": "POS-1",
        "closed_at_utc": "2026-09-29T23:30:00+00:00",
        "symbol": "BTCUSDT",
        "realized_pnl": 0.25,
    }) is True
    assert store.append({
        "position_id": "POS-2",
        "closed_at_utc": "2026-09-30T00:30:00+00:00",
        "symbol": "ETHUSDT",
        "realized_pnl": -0.25,
    }) is True

    rows = store.read_time_range(
        "closed_at_utc",
        "2026-09-29T00:00:00+00:00",
        "2026-09-30T00:00:00+00:00",
    )

    assert rows == [{
        "position_id": "POS-1",
        "closed_at_utc": "2026-09-29T23:30:00+00:00",
        "symbol": "BTCUSDT",
        "realized_pnl": 0.25,
    }]
