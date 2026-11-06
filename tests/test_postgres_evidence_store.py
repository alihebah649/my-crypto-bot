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
            if key in self.db.rows and "DO UPDATE" not in normalized:
                return _FakeResult(rowcount=0)
            self.db.rows[key] = json.loads(payload)
            return _FakeResult(rowcount=1)
        if normalized.startswith("SELECT COUNT(*)"):
            evidence_type = params[0]
            count = sum(1 for key in self.db.rows if key[0] == evidence_type)
            return _FakeResult(rows=[(count,)])
        if normalized.startswith("SELECT PAYLOAD"):
            evidence_type = params[0]
            if "IDENTITY_KEY = %S" in normalized:
                identity_key = params[1]
                payload = self.db.rows.get((evidence_type, identity_key))
                return _FakeResult(rows=[(payload,)] if payload is not None else [])
            if "IDENTITY_KEY = ANY(%S::TEXT[])" in normalized:
                identities = set(params[1])
                rows = [
                    (payload,) for (kind, identity), payload in self.db.rows.items()
                    if kind == evidence_type and identity in identities
                ]
                return _FakeResult(rows=rows)
            if "PAYLOAD ->> %S = ANY(%S::TEXT[])" in normalized:
                field = params[1]
                values = set(params[2])
                rows = [
                    (payload,) for (kind, _), payload in self.db.rows.items()
                    if kind == evidence_type and str(payload.get(field, "")) in values
                ]
                return _FakeResult(rows=rows)
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



def test_get_by_identity_fetches_only_the_matching_evidence_record(monkeypatch):
    db = _FakeDatabase()

    def connect(_url):
        return _FakeConnection(db)

    store = PostgresEvidenceStore(
        "postgres://secret@example.invalid/db",
        evidence_type="BRAIN_AUTHORITY",
        connect_factory=connect,
    )
    for index in range(1500):
        assert store.append({
            "capture_id": f"CAP-{index}",
            "symbol": "BTCUSDT",
            "context": {"score": index},
        }) is True

    def fail_read_all():
        raise AssertionError("identity lookup must not call read_all()")

    monkeypatch.setattr(store, "read_all", fail_read_all)

    assert store.get_by_identity("CAP-1499") == {
        "capture_id": "CAP-1499",
        "symbol": "BTCUSDT",
        "context": {"score": 1499},
    }
    assert store.get_by_identity("MISSING") is None
    assert store.get_by_identity("") is None


def test_summary_counts_without_loading_evidence_payloads(monkeypatch):
    db = _FakeDatabase()

    def connect(_url):
        return _FakeConnection(db)

    store = PostgresEvidenceStore(
        "postgres://secret@example.invalid/db",
        evidence_type="BRAIN_SHADOW",
        connect_factory=connect,
    )
    assert store.append({"capture_id": "CAP-1", "context": {"score": 80}}) is True
    assert store.append({"capture_id": "CAP-2", "context": {"score": 81}}) is True

    def fail_read_all():
        raise AssertionError("summary must not call read_all()")

    monkeypatch.setattr(store, "read_all", fail_read_all)

    assert store.summary() == {
        "backend": "postgres",
        "schema_version": 1,
        "evidence_type": "BRAIN_SHADOW",
        "record_count": 2,
        "last_error": None,
    }


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



def test_upsert_replaces_mutable_state_without_growing_evidence_rows():
    db = _FakeDatabase()

    def connect(_url):
        return _FakeConnection(db)

    store = PostgresEvidenceStore(
        "postgres://secret@example.invalid/db",
        evidence_type="PAPER_LAB_ACCOUNT_STATE_BYBIT",
        max_records=1,
        connect_factory=connect,
    )

    assert store.upsert({
        "record_id": "account_snapshot_v1",
        "cash": 1000.0,
        "assets": {},
    }) is True
    assert store.upsert({
        "record_id": "account_snapshot_v1",
        "cash": 987.5,
        "assets": {"BTCUSDT": 0.01},
    }) is True

    assert store.count() == 1
    assert store.read_all() == [{
        "record_id": "account_snapshot_v1",
        "cash": 987.5,
        "assets": {"BTCUSDT": 0.01},
    }]



def test_read_by_identity_keys_loads_only_matching_capture_payloads(monkeypatch):
    db = _FakeDatabase()

    def connect(_url):
        return _FakeConnection(db)

    store = PostgresEvidenceStore(
        "postgres://secret@example.invalid/db",
        evidence_type="ENTRY_V2_CAPTURE",
        connect_factory=connect,
    )
    for index in range(200):
        assert store.append({
            "capture_id": f"CAP-{index}",
            "symbol": "BTCUSDT",
            "closed_candle_windows": {"5m": [{"close": index}] * 8},
        }) is True

    def fail_read_all():
        raise AssertionError("selective identity lookup must not call read_all()")

    monkeypatch.setattr(store, "read_all", fail_read_all)
    selected = store.read_by_identity_keys(["CAP-3", "CAP-150", "CAP-3", "MISSING"])

    assert {row["capture_id"] for row in selected} == {"CAP-3", "CAP-150"}
    assert store.last_error is None


def test_read_by_payload_values_loads_only_matching_position_captures(monkeypatch):
    db = _FakeDatabase()

    def connect(_url):
        return _FakeConnection(db)

    store = PostgresEvidenceStore(
        "postgres://secret@example.invalid/db",
        evidence_type="ENTRY_V2_CAPTURE_BYBIT_HOSTED_LAB",
        connect_factory=connect,
    )
    for index in range(200):
        assert store.append({
            "capture_id": f"CAP-{index}",
            "position_id": f"POS-{index}" if index % 2 == 0 else None,
            "candidate": {"symbol": "BTCUSDT"},
        }) is True

    def fail_read_all():
        raise AssertionError("selective JSON payload lookup must not call read_all()")

    monkeypatch.setattr(store, "read_all", fail_read_all)
    selected = store.read_by_payload_values("position_id", ["POS-2", "POS-100", "POS-2"])

    assert {row["position_id"] for row in selected} == {"POS-2", "POS-100"}
    assert store.last_error is None
