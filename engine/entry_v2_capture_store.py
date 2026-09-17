"""Durable JSONL store for non-authoritative Entry v2 shadow captures.

The store is intentionally independent from execution and Trade Manager. It
keeps one immutable capture per observed Legacy BUY candidate so Paper Trading
can accumulate evidence across process restarts without changing trading
behavior.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Iterable, Mapping


class EntryV2CaptureStore:
    """Append-only JSONL persistence with bounded record retention."""

    def __init__(self, path: str | os.PathLike[str], *, max_records: int = 10_000) -> None:
        if max_records <= 0:
            raise ValueError("max_records must be positive")
        self.path = Path(path)
        self.max_records = int(max_records)
        self._lock = threading.RLock()
        self._record_count = self._count_records()
        self.last_error: str | None = None

    def _count_records(self) -> int:
        if not self.path.exists():
            return 0
        count = 0
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if line.strip():
                        try:
                            json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        count += 1
        except OSError:
            return 0
        return count

    @staticmethod
    def _safe(record: Mapping[str, Any]) -> dict[str, Any]:
        def convert(value: Any) -> Any:
            if isinstance(value, Mapping):
                return {str(k): convert(v) for k, v in value.items()}
            if isinstance(value, (list, tuple)):
                return [convert(v) for v in value]
            if isinstance(value, (str, int, float, bool)) or value is None:
                return value
            return str(value)
        return convert(record)

    def append(self, record: Mapping[str, Any]) -> bool:
        return self.append_many((record,)) == 1

    def append_many(self, records: Iterable[Mapping[str, Any]]) -> int:
        prepared = [self._safe(record) for record in records]
        if not prepared:
            return 0
        with self._lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as handle:
                    for record in prepared:
                        handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                self._record_count += len(prepared)
                self.last_error = None
                self._compact_if_needed()
                return len(prepared)
            except OSError as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"
                return 0

    def _compact_if_needed(self) -> None:
        if self._record_count <= self.max_records:
            return
        records = self.read_all()[-self.max_records :]
        directory = str(self.path.parent)
        fd, temp_name = tempfile.mkstemp(prefix=f".{self.path.name}.", suffix=".tmp", dir=directory, text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                for record in records:
                    handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self.path)
            self._record_count = len(records)
        except OSError:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
            raise

    def read_all(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        records: list[dict[str, Any]] = []
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        value = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(value, dict):
                        records.append(value)
        except OSError as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
        return records

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        if limit <= 0:
            return []
        return self.read_all()[-int(limit) :]

    def count(self) -> int:
        with self._lock:
            return int(self._record_count)

    def summary(self) -> dict[str, Any]:
        records = self.read_all()
        approved = rejected = 0
        lanes: dict[str, int] = {}
        gates: dict[str, int] = {}
        for record in records:
            decision = record.get("v2_decision", {}) or {}
            if decision.get("approved") is True:
                approved += 1
            elif decision.get("approved") is False:
                rejected += 1
            lane = str(decision.get("trade_mode") or record.get("legacy_result", {}).get("trade_mode") or "UNKNOWN").upper()
            lanes[lane] = lanes.get(lane, 0) + 1
            gate = decision.get("failed_gate") or "NONE"
            gates[str(gate)] = gates.get(str(gate), 0) + 1
        return {
            "path": str(self.path),
            "record_count": len(records),
            "approved": approved,
            "rejected": rejected,
            "lanes": lanes,
            "failed_gates": gates,
            "last_error": self.last_error,
        }


__all__ = ["EntryV2CaptureStore"]
