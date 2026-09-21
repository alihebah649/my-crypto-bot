from __future__ import annotations

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
            self.db.rows[key] = payload
            return _FakeResult(rowcount=1)
        if normalized.startswith("SELECT COUNT(*)"):
            evidence_type = params[0]
            count = sum(1 for key in self.db.rows if key[0] == evidence_type)
            return _FakeResult(rows=[(count,)])
        if normalized.startswith("SELECT PAYLOAD"):
            evidence_type = params[0]
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
