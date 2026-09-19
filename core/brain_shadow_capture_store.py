"""Durable JSONL evidence store for Brain shadow observations.

This store is diagnostic-only. It persists Brain entry observations so that
Paper Trading can compare Brain advice with actual Legacy execution outcomes
across process restarts without changing execution authority.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Iterable, Mapping


class BrainShadowCaptureStore:
    """Append-only JSONL store with lightweight retention and corruption tolerance."""

    def __init__(self, path: str | os.PathLike[str], *, max_records: int = 50_000) -> None:
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
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    count += 1
        except OSError:
            return 0
        return count

    @staticmethod
    def _safe(value: Any) -> Any:
        if isinstance(value, Mapping):
            return {str(k): BrainShadowCaptureStore._safe(v) for k, v in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [BrainShadowCaptureStore._safe(v) for v in value]
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return str(value)

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
        try:
            with self.path.open("w", encoding="utf-8") as handle:
                for record in records:
                    handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            self._record_count = len(records)
        except OSError as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"

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

    def count(self) -> int:
        with self._lock:
            return int(self._record_count)

    def summary(self) -> dict[str, Any]:
        records = self.read_all()
        return {
            "path": str(self.path),
            "record_count": len(records),
            "last_error": self.last_error,
        }


__all__ = ["BrainShadowCaptureStore"]
