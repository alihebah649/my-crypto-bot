"""TTL cache for closed 1h/4h multi-timeframe candle context.

The cache is deliberately separate from strategy scoring so the fast 5m/15m
execution path does not need to know about refresh policy.  Cached payloads are
only considered usable while fresh; callers should still pass only closed
candles into the strategy layer.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class MTFCacheEntry:
    candles: List[dict]
    refreshed_at: float


class MTFContextCache:
    """Small in-memory TTL cache keyed by symbol/timeframe."""

    def __init__(self, ttl_by_timeframe: Optional[Dict[str, float]] = None, clock=None):
        self.ttl_by_timeframe = dict(ttl_by_timeframe or {"1h": 3300.0, "4h": 14100.0})
        self._clock = clock or time.monotonic
        self._entries: Dict[tuple[str, str], MTFCacheEntry] = {}

    def get(self, symbol: str, timeframe: str) -> Optional[List[dict]]:
        entry = self._entries.get((symbol, timeframe))
        if entry is None:
            return None
        ttl = float(self.ttl_by_timeframe.get(timeframe, 0.0))
        if ttl <= 0.0 or self._clock() - entry.refreshed_at >= ttl:
            self._entries.pop((symbol, timeframe), None)
            return None
        return entry.candles

    def put(self, symbol: str, timeframe: str, candles: List[dict]) -> None:
        self._entries[(symbol, timeframe)] = MTFCacheEntry(
            candles=list(candles),
            refreshed_at=self._clock(),
        )

    def clear(self) -> None:
        self._entries.clear()

    def size(self) -> int:
        return len(self._entries)
