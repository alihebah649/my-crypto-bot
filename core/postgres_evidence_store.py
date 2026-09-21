"""Optional durable Postgres store for Paper/Shadow evidence.

The store is diagnostic-only. It is compatible with the append/read interface
used by the existing JSONL evidence stores, so enabling it does not change
strategy, risk, Trade Manager, or execution authority.

The database URL is supplied by the runtime environment and is never persisted
in the repository or returned by diagnostics.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from typing import Any, Callable, Iterable, Mapping


class PostgresEvidenceStore:
    """Append-only, idempotent evidence store backed by Render Postgres."""

    SCHEMA_VERSION = 1

    def __init__(
        self,
        database_url: str,
        *,
        evidence_type: str,
        max_records: int = 50_000,
        connect_factory: Callable[..., Any] | None = None,
    ) -> None:
        if not database_url:
            raise ValueError("database_url is required")
        if not evidence_type:
            raise ValueError("evidence_type is required")
        if max_records <= 0:
            raise ValueError("max_records must be positive")
        self.database_url = str(database_url)
        self.evidence_type = str(evidence_type)
        self.max_records = int(max_records)
        self._connect_factory = connect_factory
        self._lock = threading.RLock()
        self._conn: Any | None = None
        self.last_error: str | None = None
        self._initialized = False

    @staticmethod
    def _safe(value: Any) -> Any:
        if isinstance(value, Mapping):
            return {str(k): PostgresEvidenceStore._safe(v) for k, v in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [PostgresEvidenceStore._safe(v) for v in value]
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return str(value)

    def _connect(self) -> Any:
        if self._conn is not None and not getattr(self._conn, "closed", False):
            return self._conn
        if self._connect_factory is not None:
            self._conn = self._connect_factory(self.database_url)
            return self._conn
        try:
            import psycopg
        except ImportError as exc:  # pragma: no cover - exercised by deployment
            raise RuntimeError("psycopg is required for Postgres evidence storage") from exc
        self._conn = psycopg.connect(self.database_url, connect_timeout=5)
        return self._conn

    def _reset_connection(self) -> None:
        conn = self._conn
        self._conn = None
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    def _ensure_schema(self) -> None:
        if self._initialized:
            return
        conn = self._connect()
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_evidence (
                id BIGSERIAL PRIMARY KEY,
                evidence_type TEXT NOT NULL,
                identity_key TEXT NOT NULL,
                recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                payload JSONB NOT NULL,
                UNIQUE (evidence_type, identity_key)
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_paper_evidence_type_recorded
            ON paper_evidence (evidence_type, recorded_at, id)
            """
        )
        conn.commit()
        self._initialized = True

    def _identity_key(self, record: Mapping[str, Any]) -> str:
        for field in ("capture_id", "position_id", "record_id", "id"):
            value = record.get(field)
            if value:
                return str(value)
        canonical = json.dumps(
            self._safe(record),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def append(self, record: Mapping[str, Any]) -> bool:
        return self.append_many((record,)) == 1

    def append_many(self, records: Iterable[Mapping[str, Any]]) -> int:
        prepared = [self._safe(record) for record in records]
        if not prepared:
            return 0
        with self._lock:
            for attempt in range(2):
                try:
                    conn = self._connect()
                    self._ensure_schema()
                    inserted = 0
                    for record in prepared:
                        key = self._identity_key(record)
                        result = conn.execute(
                            """
                            INSERT INTO paper_evidence
                                (evidence_type, identity_key, payload)
                            VALUES (%s, %s, %s::jsonb)
                            ON CONFLICT (evidence_type, identity_key) DO NOTHING
                            """,
                            (
                                self.evidence_type,
                                key,
                                json.dumps(record, ensure_ascii=False, separators=(",", ":")),
                            ),
                        )
                        inserted += int(getattr(result, "rowcount", 0) or 0)
                    conn.commit()
                    self.last_error = None
                    self._compact_if_needed(conn)
                    return inserted
                except Exception as exc:
                    self.last_error = f"{type(exc).__name__}: {exc}"
                    self._reset_connection()
                    self._initialized = False
                    if attempt == 1:
                        return 0
        return 0

    def _compact_if_needed(self, conn: Any) -> None:
        # Evidence volume in this experiment is expected to remain well below
        # the bound. Keep the retention rule explicit without deleting history
        # during normal operation unless the configured ceiling is exceeded.
        row = conn.execute(
            "SELECT COUNT(*) FROM paper_evidence WHERE evidence_type = %s",
            (self.evidence_type,),
        ).fetchone()
        count = int(row[0]) if row else 0
        if count <= self.max_records:
            return
        delete_count = count - self.max_records
        conn.execute(
            """
            DELETE FROM paper_evidence
            WHERE id IN (
                SELECT id
                FROM paper_evidence
                WHERE evidence_type = %s
                ORDER BY recorded_at ASC, id ASC
                LIMIT %s
            )
            """,
            (self.evidence_type, delete_count),
        )
        conn.commit()

    def read_all(self) -> list[dict[str, Any]]:
        with self._lock:
            for attempt in range(2):
                try:
                    self._ensure_schema()
                    rows = self._connect().execute(
                        """
                        SELECT payload
                        FROM paper_evidence
                        WHERE evidence_type = %s
                        ORDER BY id ASC
                        """,
                        (self.evidence_type,),
                    ).fetchall()
                    self.last_error = None
                    return [dict(row[0]) for row in rows if isinstance(row[0], Mapping)]
                except Exception as exc:
                    self.last_error = f"{type(exc).__name__}: {exc}"
                    self._reset_connection()
                    self._initialized = False
                    if attempt == 1:
                        return []
        return []

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        if limit <= 0:
            return []
        records = self.read_all()
        return records[-int(limit):]

    def count(self) -> int:
        return len(self.read_all())

    def summary(self) -> dict[str, Any]:
        records = self.read_all()
        return {
            "backend": "postgres",
            "schema_version": self.SCHEMA_VERSION,
            "evidence_type": self.evidence_type,
            "record_count": len(records),
            "last_error": self.last_error,
        }

    def close(self) -> None:
        with self._lock:
            self._reset_connection()
            self._initialized = False


def database_url_from_env() -> str | None:
    value = os.getenv("PAPER_EVIDENCE_DATABASE_URL") or os.getenv("DATABASE_URL")
    value = str(value or "").strip()
    return value or None


__all__ = ["PostgresEvidenceStore", "database_url_from_env"]
