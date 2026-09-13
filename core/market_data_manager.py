"""Persistent, rate-aware market-data cache primitives for Paper Trading.

This module deliberately contains no strategy or execution logic. It provides
one place to store market snapshots with per-dataset freshness, staggered
symbol groups, and a safe distinction between data that may be analyzed and
data that may be used for a new paper entry.
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping


@dataclass(frozen=True)
class CachePolicy:
    """Freshness policy for one market-data dataset."""

    fresh_ttl_seconds: float
    stale_max_age_seconds: float


@dataclass(frozen=True)
class CacheSnapshot:
    """A stored payload plus its acquisition timestamp."""

    fetched_at: float
    payload: Any

    @property
    def age_seconds(self) -> float:
        return max(0.0, time.time() - self.fetched_at)


class PersistentMarketDataCache:
    """Small atomic JSON-backed cache intended for the Paper state directory."""

    def __init__(self, path: str | os.PathLike[str]):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._data: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                raw = json.load(handle)
            self._data = raw if isinstance(raw, dict) else {}
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            self._data = {}

    def _save(self) -> None:
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(self._data, handle, ensure_ascii=False, separators=(",", ":"))
        os.replace(temporary, self.path)

    def put(self, key: str, payload: Any, *, fetched_at: float | None = None) -> None:
        with self._lock:
            self._data[str(key)] = {
                "fetched_at": float(time.time() if fetched_at is None else fetched_at),
                "payload": payload,
            }
            self._save()

    def get(self, key: str) -> CacheSnapshot | None:
        with self._lock:
            row = self._data.get(str(key))
            if not isinstance(row, dict) or "fetched_at" not in row:
                return None
            try:
                return CacheSnapshot(float(row["fetched_at"]), row.get("payload"))
            except (TypeError, ValueError):
                return None

    def keys(self) -> list[str]:
        with self._lock:
            return list(self._data)


class MarketDataManager:
    """Coordinates cache reads and staggered REST refreshes.

    The manager never decides whether a trade is profitable or halal; it only
    answers whether a cached market snapshot is fresh enough for a purpose.
    """

    def __init__(
        self,
        cache: PersistentMarketDataCache,
        *,
        ticker_symbols: Iterable[str],
        ticker_batch_size: int = 11,
        ticker_group_interval_seconds: float = 30.0,
        policies: Mapping[str, CachePolicy] | None = None,
    ):
        symbols = [str(symbol).upper() for symbol in ticker_symbols]
        if ticker_batch_size <= 0:
            raise ValueError("ticker_batch_size must be positive")
        if ticker_group_interval_seconds <= 0:
            raise ValueError("ticker_group_interval_seconds must be positive")
        self.cache = cache
        self.symbols = symbols
        self.ticker_batch_size = int(ticker_batch_size)
        self.ticker_group_interval_seconds = float(ticker_group_interval_seconds)
        self.policies = dict(policies or {
            "ticker": CachePolicy(fresh_ttl_seconds=75.0, stale_max_age_seconds=300.0),
            "5m": CachePolicy(fresh_ttl_seconds=310.0, stale_max_age_seconds=900.0),
            "15m": CachePolicy(fresh_ttl_seconds=910.0, stale_max_age_seconds=1800.0),
            "1h": CachePolicy(fresh_ttl_seconds=3610.0, stale_max_age_seconds=7200.0),
            "4h": CachePolicy(fresh_ttl_seconds=14410.0, stale_max_age_seconds=28800.0),
        })
        self._lock = threading.RLock()
        self._next_ticker_group = 0
        self._next_ticker_refresh_at = 0.0

    def ticker_groups(self) -> list[list[str]]:
        """Return deterministic ticker groups (22 -> 11 + 11)."""
        return [
            self.symbols[start : start + self.ticker_batch_size]
            for start in range(0, len(self.symbols), self.ticker_batch_size)
        ]

    def should_refresh(self, dataset: str, key: str, *, now: float | None = None) -> bool:
        policy = self.policies[dataset]
        snapshot = self.cache.get(key)
        if snapshot is None:
            return True
        current = time.time() if now is None else float(now)
        return current - snapshot.fetched_at >= policy.fresh_ttl_seconds

    def get_for_analysis(self, dataset: str, key: str, *, now: float | None = None) -> CacheSnapshot | None:
        """Return fresh or bounded-stale data for diagnostics/analysis."""
        policy = self.policies[dataset]
        snapshot = self.cache.get(key)
        if snapshot is None:
            return None
        current = time.time() if now is None else float(now)
        age = max(0.0, current - snapshot.fetched_at)
        if age <= policy.stale_max_age_seconds:
            return snapshot
        return None

    def entry_data_is_fresh(self, dataset: str, key: str, *, now: float | None = None) -> bool:
        """Return True only when data is inside its fresh TTL."""
        policy = self.policies[dataset]
        snapshot = self.cache.get(key)
        if snapshot is None:
            return False
        current = time.time() if now is None else float(now)
        return max(0.0, current - snapshot.fetched_at) < policy.fresh_ttl_seconds

    def refresh_ticker_group(
        self,
        fetch_batch: Callable[[list[str]], Mapping[str, Any]],
        *,
        now: float | None = None,
    ) -> dict[str, Any]:
        """Fetch at most one ticker group and merge it into the persistent cache."""
        current = time.time() if now is None else float(now)
        with self._lock:
            if current < self._next_ticker_refresh_at:
                return {}
            groups = self.ticker_groups()
            if not groups:
                return {}
            group = groups[self._next_ticker_group % len(groups)]
            fetched = dict(fetch_batch(group))
            for symbol in group:
                if symbol in fetched:
                    self.cache.put(f"ticker:{symbol}", fetched[symbol], fetched_at=current)
            self._next_ticker_group = (self._next_ticker_group + 1) % len(groups)
            self._next_ticker_refresh_at = current + self.ticker_group_interval_seconds
            return {symbol: fetched[symbol] for symbol in group if symbol in fetched}

    def merged_ticker_snapshot(self) -> dict[str, Any]:
        """Return all symbols whose ticker snapshot is still bounded-stale."""
        result: dict[str, Any] = {}
        for symbol in self.symbols:
            snapshot = self.get_for_analysis("ticker", f"ticker:{symbol}")
            if snapshot is not None:
                result[symbol] = snapshot.payload
        return result

    def freshness_report(self) -> dict[str, Any]:
        report: dict[str, Any] = {}
        now = time.time()
        for dataset, policy in self.policies.items():
            entries: list[dict[str, Any]] = []
            prefix = f"{dataset}:"
            for key in self.cache.keys():
                if key != dataset and not key.startswith(prefix):
                    continue
                snapshot = self.cache.get(key)
                if snapshot is None:
                    continue
                age = max(0.0, now - snapshot.fetched_at)
                entries.append({
                    "key": key,
                    "age_seconds": round(age, 3),
                    "fresh": age < policy.fresh_ttl_seconds,
                    "analysis_available": age <= policy.stale_max_age_seconds,
                    "entry_safe": age < policy.fresh_ttl_seconds,
                })
            report[dataset] = {
                "fresh_ttl_seconds": policy.fresh_ttl_seconds,
                "stale_max_age_seconds": policy.stale_max_age_seconds,
                "entries": entries,
            }
        return report
