from __future__ import annotations

import threading
import time
from collections import Counter
from typing import Any, Callable

from core.entry_freshness_audit import audit_5m_entry_freshness


def install(*, legacy: Any, kline_cache: dict, kline_cache_lock: threading.RLock, kline_cache_ttl: dict[str, float]) -> Callable[[], dict]:
    """Install diagnostics around the already-patched market-data wrappers."""
    if getattr(legacy, "_market_data_runtime_trace_installed", False):
        return legacy._market_data_runtime_trace_snapshot

    lock = threading.RLock()
    stats = {
        "fetch_strategy_calls": 0,
        "fetch_strategy_last_started_at": None,
        "fetch_strategy_last_finished_at": None,
        "fetch_strategy_last_elapsed_seconds": None,
        "kline_calls": 0,
        "kline_hits": 0,
        "kline_expired_or_missing": 0,
        "kline_refreshes": 0,
        "kline_empty_returns": 0,
        "entry_freshness_audits": 0,
    }
    by_interval: Counter[str] = Counter()
    hits_by_interval: Counter[str] = Counter()
    stale_by_interval: Counter[str] = Counter()
    refresh_by_interval: Counter[str] = Counter()
    empty_by_interval: Counter[str] = Counter()
    freshness_by_state: Counter[str] = Counter()
    last_events: list[dict[str, Any]] = []
    original_fetch_klines = legacy.fetch_klines
    original_fetch_strategy_data = legacy.fetch_strategy_data
    original_score_symbol = legacy.score_symbol

    def snapshot() -> dict[str, Any]:
        now = time.time()
        with lock:
            data = dict(stats)
            data["kline_calls_by_interval"] = dict(by_interval)
            data["kline_hits_by_interval"] = dict(hits_by_interval)
            data["kline_expired_or_missing_by_interval"] = dict(stale_by_interval)
            data["kline_refreshes_by_interval"] = dict(refresh_by_interval)
            data["kline_empty_returns_by_interval"] = dict(empty_by_interval)
            data["entry_freshness_by_state"] = dict(freshness_by_state)
            data["last_events"] = list(last_events)
        data["captured_at"] = now
        return data

    def traced_fetch_klines(symbol: str, interval: str, limit: int):
        key = (str(symbol).upper(), str(interval), int(limit))
        now = time.time()
        with kline_cache_lock:
            cached = kline_cache.get(key)
            cache_age = None if cached is None else max(0.0, now - cached[0])
            ttl = float(kline_cache_ttl.get(str(interval), 0.0))
            fresh = bool(cached is not None and cache_age is not None and cache_age < ttl)

        with lock:
            stats["kline_calls"] += 1
            by_interval[str(interval)] += 1
            if fresh:
                stats["kline_hits"] += 1
                hits_by_interval[str(interval)] += 1
            else:
                stats["kline_expired_or_missing"] += 1
                stale_by_interval[str(interval)] += 1

        result = original_fetch_klines(symbol, interval, limit)

        with kline_cache_lock:
            after = kline_cache.get(key)
            refreshed = bool(
                after is not None
                and (cached is None or float(after[0]) != float(cached[0]))
            )
        with lock:
            if refreshed:
                stats["kline_refreshes"] += 1
                refresh_by_interval[str(interval)] += 1
            if not result:
                stats["kline_empty_returns"] += 1
                empty_by_interval[str(interval)] += 1
            last_events.append({
                "at": time.time(),
                "symbol": str(symbol).upper(),
                "interval": str(interval),
                "limit": int(limit),
                "cache_before": "HIT" if fresh else ("MISS" if cached is None else "EXPIRED"),
                "cache_age_before_seconds": None if cache_age is None else round(cache_age, 1),
                "ttl_seconds": ttl,
                "cache_after_refresh": refreshed,
                "returned_rows": len(result) if isinstance(result, list) else None,
            })
            del last_events[:-40]
        return result

    def traced_fetch_strategy_data():
        started = time.time()
        with lock:
            stats["fetch_strategy_calls"] += 1
            stats["fetch_strategy_last_started_at"] = started
        try:
            return original_fetch_strategy_data()
        finally:
            finished = time.time()
            with lock:
                stats["fetch_strategy_last_finished_at"] = finished
                stats["fetch_strategy_last_elapsed_seconds"] = round(finished - started, 3)
                summary = snapshot()
                legacy.logger.info(
                    "[MARKET-DATA-TRACE] strategy_call=%d elapsed=%.3fs "
                    "kline_calls=%d hits=%d stale_or_missing=%d refreshes=%d empty=%d "
                    "by_interval=%s refresh_by_interval=%s",
                    summary["fetch_strategy_calls"],
                    summary["fetch_strategy_last_elapsed_seconds"] or 0.0,
                    summary["kline_calls"],
                    summary["kline_hits"],
                    summary["kline_expired_or_missing"],
                    summary["kline_refreshes"],
                    summary["kline_empty_returns"],
                    summary["kline_calls_by_interval"],
                    summary["kline_refreshes_by_interval"],
                )

    def traced_score_symbol(symbol: str, ticker: dict, candles_15m: list[dict], candles_5m: list[dict]):
        """Attach exact 5m decision-candle freshness without changing scoring."""
        result = original_score_symbol(symbol, ticker, candles_15m, candles_5m)
        symbol_key = str(symbol).upper()
        cache_key = (symbol_key, "5m", 60)
        with kline_cache_lock:
            cached = kline_cache.get(cache_key)
            cache_timestamp = None if cached is None else float(cached[0])
            cache_ttl = float(kline_cache_ttl.get("5m", 0.0))
        audit = audit_5m_entry_freshness(
            candles_5m=candles_5m,
            captured_at=time.time(),
            cache_timestamp=cache_timestamp,
            cache_ttl_seconds=cache_ttl,
        )
        if isinstance(result, dict):
            result["entry_freshness_5m"] = audit
        with lock:
            stats["entry_freshness_audits"] += 1
            freshness_by_state[str(audit.get("state", "UNKNOWN"))] += 1
            last_events.append({
                "at": time.time(),
                "event": "ENTRY_FRESHNESS_AUDIT",
                "symbol": symbol_key,
                "state": audit.get("state"),
                "decision_candle_close_time_ms": audit.get("decision_candle_close_time_ms"),
                "decision_candle_age_seconds": audit.get("decision_candle_age_seconds"),
                "cache_age_seconds": audit.get("cache_age_seconds"),
                "cache_expired": audit.get("cache_expired"),
            })
            del last_events[:-40]
        return result

    legacy.fetch_klines = traced_fetch_klines
    legacy.fetch_strategy_data = traced_fetch_strategy_data
    legacy.score_symbol = traced_score_symbol
    legacy._market_data_runtime_trace_installed = True
    legacy._market_data_runtime_trace_snapshot = snapshot
    return snapshot
