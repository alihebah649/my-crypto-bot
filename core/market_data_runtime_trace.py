from __future__ import annotations

import threading
import time
from collections import Counter
from typing import Any, Callable

from core.entry_freshness_audit import audit_5m_entry_freshness


def install(*, legacy: Any, kline_cache: dict, kline_cache_lock: threading.RLock, kline_cache_ttl: dict[str, float]) -> Callable[[], dict]:
    """Install diagnostics around the active market-data path.

    Freshness is read from ``legacy.market_data_manager.cache`` when that
    manager is installed, because that is the cache actually consumed by
    ``managed_kline``. The legacy in-memory cache remains a fallback only.
    """
    if getattr(legacy, "_market_data_runtime_trace_installed", False):
        return legacy._market_data_runtime_trace_snapshot

    lock = threading.RLock()
    stats = {"fetch_strategy_calls": 0, "fetch_strategy_last_started_at": None, "fetch_strategy_last_finished_at": None, "fetch_strategy_last_elapsed_seconds": None, "kline_calls": 0, "kline_hits": 0, "kline_expired_or_missing": 0, "kline_refreshes": 0, "kline_empty_returns": 0, "entry_freshness_audits": 0}
    by_interval: Counter[str] = Counter(); hits_by_interval: Counter[str] = Counter(); stale_by_interval: Counter[str] = Counter(); refresh_by_interval: Counter[str] = Counter(); empty_by_interval: Counter[str] = Counter(); freshness_by_state: Counter[str] = Counter(); last_events: list[dict[str, Any]] = []
    original_fetch_klines = legacy.fetch_klines
    original_fetch_strategy_data = legacy.fetch_strategy_data
    original_score_symbol = legacy.score_symbol

    def _cache_observation(symbol: str, interval: str, limit: int, now: float) -> dict[str, Any]:
        symbol_key, interval_key = str(symbol).upper(), str(interval)
        key = f"{interval_key}:{symbol_key}:{int(limit)}"
        manager = getattr(legacy, "market_data_manager", None)
        if manager is not None:
            try:
                cached = manager.cache.get(key)
                policy = manager.policies.get(interval_key)
                ttl = None if policy is None else float(policy.fresh_ttl_seconds)
                if cached is None:
                    return {"source": "PersistentMarketDataCache", "cache_key": key, "cache_timestamp": None, "cache_age_seconds": None, "cache_ttl_seconds": ttl, "cache_expired": True}
                age = max(0.0, now - float(cached.fetched_at))
                return {"source": "PersistentMarketDataCache", "cache_key": key, "cache_timestamp": float(cached.fetched_at), "cache_age_seconds": round(age, 3), "cache_ttl_seconds": ttl, "cache_expired": None if ttl is None else age >= ttl}
            except Exception:
                pass
        key_tuple = (symbol_key, interval_key, int(limit))
        with kline_cache_lock:
            cached = kline_cache.get(key_tuple); ttl = float(kline_cache_ttl.get(interval_key, 0.0))
        age = None if cached is None else max(0.0, now - float(cached[0]))
        return {"source": "legacy_kline_cache", "cache_key": key_tuple, "cache_timestamp": None if cached is None else float(cached[0]), "cache_age_seconds": None if age is None else round(age, 3), "cache_ttl_seconds": ttl, "cache_expired": None if age is None else age >= ttl}

    def snapshot() -> dict[str, Any]:
        now = time.time()
        with lock:
            data = dict(stats)
            data.update({"kline_calls_by_interval": dict(by_interval), "kline_hits_by_interval": dict(hits_by_interval), "kline_expired_or_missing_by_interval": dict(stale_by_interval), "kline_refreshes_by_interval": dict(refresh_by_interval), "kline_empty_returns_by_interval": dict(empty_by_interval), "entry_freshness_by_state": dict(freshness_by_state), "last_events": list(last_events)})
        manager = getattr(legacy, "market_data_manager", None)
        if manager is not None:
            data["market_data_cache_source"] = "PersistentMarketDataCache"
            try: data["market_data_freshness_report"] = manager.freshness_report()
            except Exception as exc: data["market_data_freshness_report_error"] = str(exc)
        else:
            data["market_data_cache_source"] = "legacy_kline_cache"
        data["captured_at"] = now
        return data

    def traced_fetch_klines(symbol: str, interval: str, limit: int):
        key = (str(symbol).upper(), str(interval), int(limit)); now = time.time()
        with kline_cache_lock:
            cached = kline_cache.get(key); cache_age = None if cached is None else max(0.0, now - cached[0]); ttl = float(kline_cache_ttl.get(str(interval), 0.0)); fresh = bool(cached is not None and cache_age is not None and cache_age < ttl)
        with lock:
            stats["kline_calls"] += 1; by_interval[str(interval)] += 1
            if fresh: stats["kline_hits"] += 1; hits_by_interval[str(interval)] += 1
            else: stats["kline_expired_or_missing"] += 1; stale_by_interval[str(interval)] += 1
        result = original_fetch_klines(symbol, interval, limit)
        with kline_cache_lock:
            after = kline_cache.get(key); refreshed = bool(after is not None and (cached is None or float(after[0]) != float(cached[0])))
        with lock:
            if refreshed: stats["kline_refreshes"] += 1; refresh_by_interval[str(interval)] += 1
            if not result: stats["kline_empty_returns"] += 1; empty_by_interval[str(interval)] += 1
            last_events.append({"at": time.time(), "symbol": str(symbol).upper(), "interval": str(interval), "limit": int(limit), "cache_before": "HIT" if fresh else ("MISS" if cached is None else "EXPIRED"), "cache_age_before_seconds": None if cache_age is None else round(cache_age, 1), "ttl_seconds": ttl, "cache_after_refresh": refreshed, "returned_rows": len(result) if isinstance(result, list) else None}); del last_events[:-40]
        return result

    def traced_fetch_strategy_data():
        started = time.time()
        with lock: stats["fetch_strategy_calls"] += 1; stats["fetch_strategy_last_started_at"] = started
        try: return original_fetch_strategy_data()
        finally:
            finished = time.time()
            with lock:
                stats["fetch_strategy_last_finished_at"] = finished; stats["fetch_strategy_last_elapsed_seconds"] = round(finished - started, 3); summary = snapshot()
                legacy.logger.info("[MARKET-DATA-TRACE] strategy_call=%d elapsed=%.3fs kline_calls=%d hits=%d stale_or_missing=%d refreshes=%d empty=%d by_interval=%s refresh_by_interval=%s source=%s", summary["fetch_strategy_calls"], summary["fetch_strategy_last_elapsed_seconds"] or 0.0, summary["kline_calls"], summary["kline_hits"], summary["kline_expired_or_missing"], summary["kline_refreshes"], summary["kline_empty_returns"], summary["kline_calls_by_interval"], summary["kline_refreshes_by_interval"], summary.get("market_data_cache_source"))

    def traced_score_symbol(symbol: str, ticker: dict, candles_15m: list[dict], candles_5m: list[dict]):
        captured_at = time.time(); result = original_score_symbol(symbol, ticker, candles_15m, candles_5m); observation = _cache_observation(symbol, "5m", 60, captured_at)
        audit = audit_5m_entry_freshness(candles_5m=candles_5m, captured_at=captured_at, cache_timestamp=observation.get("cache_timestamp"), cache_ttl_seconds=observation.get("cache_ttl_seconds")); audit.update({"cache_source": observation.get("source"), "cache_key": observation.get("cache_key"), "snapshot_at": captured_at})
        if isinstance(result, dict): result["entry_freshness_5m"] = audit
        with lock:
            stats["entry_freshness_audits"] += 1; freshness_by_state[str(audit.get("state", "UNKNOWN"))] += 1
            last_events.append({"at": captured_at, "event": "ENTRY_FRESHNESS_AUDIT", "symbol": str(symbol).upper(), "state": audit.get("state"), "snapshot_at": captured_at, "cache_source": observation.get("source"), "cache_key": observation.get("cache_key"), "cache_timestamp": observation.get("cache_timestamp"), "decision_candle_open_time_ms": audit.get("decision_candle_open_time_ms"), "decision_candle_close_time_ms": audit.get("decision_candle_close_time_ms"), "decision_candle_age_seconds": audit.get("decision_candle_age_seconds"), "cache_age_seconds": observation.get("cache_age_seconds"), "cache_ttl_seconds": observation.get("cache_ttl_seconds"), "cache_expired": observation.get("cache_expired")}); del last_events[:-40]
        return result

    legacy.fetch_klines = traced_fetch_klines
    legacy.fetch_strategy_data = traced_fetch_strategy_data
    legacy.score_symbol = traced_score_symbol
    legacy._market_data_runtime_trace_installed = True
    legacy._market_data_runtime_trace_snapshot = snapshot
    return snapshot
