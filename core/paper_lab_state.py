"""Compact PostgreSQL persistence for independent Paper venue-lab runtimes.

Each lab owns one mutable runtime snapshot in the existing paper_evidence table.
The snapshot is keyed by venue, updated in place, and never shares the MAIN
portfolio. Closed outcomes remain append-only in their own evidence types.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from core.postgres_evidence_store import PostgresEvidenceStore
from trade_manager.repository import PositionRepository


_SUPPORTED_VENUES = {"BINANCE", "BYBIT", "OKX"}
_STATE_RECORD_ID = "paper_venue_lab_runtime_v1"


class PostgresPaperLabState:
    """Persist one venue's Paper account and Trade Manager positions atomically."""

    SCHEMA_VERSION = 1

    def __init__(
        self,
        database_url: str,
        *,
        venue: str,
        connect_factory=None,
    ) -> None:
        normalized = str(venue or "").strip().upper()
        if normalized not in _SUPPORTED_VENUES:
            raise ValueError(f"unsupported Paper lab venue: {venue!r}")
        if not database_url:
            raise ValueError("database_url is required")
        self.venue = normalized
        self.store = PostgresEvidenceStore(
            database_url,
            evidence_type=f"PAPER_LAB_STATE_{normalized}",
            max_records=1,
            connect_factory=connect_factory,
        )
        self._last_state_hash: str | None = None

    @property
    def last_error(self) -> str | None:
        return self.store.last_error

    def load_into(self, execution_adapter, position_repository: PositionRepository) -> bool:
        """Restore state or raise; never silently start an empty account on DB failure."""
        records = self.store.read_all()
        if self.store.last_error:
            raise RuntimeError(
                f"Unable to read {self.venue} Paper lab state: {self.store.last_error}"
            )
        if not records:
            self._last_state_hash = None
            return False

        record = records[-1]
        if record.get("record_id") != _STATE_RECORD_ID:
            raise RuntimeError(f"invalid {self.venue} Paper lab state record identity")
        if int(record.get("schema_version", 0) or 0) != self.SCHEMA_VERSION:
            raise RuntimeError(f"unsupported {self.venue} Paper lab state schema")

        account = record.get("account")
        positions = record.get("positions")
        if not isinstance(account, dict) or not isinstance(positions, dict):
            raise RuntimeError(f"incomplete {self.venue} Paper lab state snapshot")
        execution_adapter.restore_snapshot(account)
        position_repository.restore_snapshot(positions)
        self._last_state_hash = self._snapshot_hash(account, positions)
        return True

    def save(self, execution_adapter, position_repository: PositionRepository) -> bool:
        """Write only when account or position state changed.

        Market prices are live observations and are intentionally omitted: they
        are repopulated from the venue WebSocket after restart, avoiding a DB
        write every market cycle.
        """
        account = execution_adapter.export_snapshot()
        account["market_prices"] = {}
        positions = position_repository.export_snapshot()
        state_hash = self._snapshot_hash(account, positions)
        if state_hash == self._last_state_hash:
            return False

        record = {
            "record_id": _STATE_RECORD_ID,
            "schema_version": self.SCHEMA_VERSION,
            "venue": self.venue,
            "account": account,
            "positions": positions,
        }
        if not self.store.upsert(record):
            raise RuntimeError(
                f"Unable to persist {self.venue} Paper lab state: "
                f"{self.store.last_error or 'upsert returned false'}"
            )
        self._last_state_hash = state_hash
        return True

    @staticmethod
    def _snapshot_hash(account: dict[str, Any], positions: dict[str, Any]) -> str:
        canonical = json.dumps(
            {"account": account, "positions": positions},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def close(self) -> None:
        self.store.close()


__all__ = ["PostgresPaperLabState"]
