from __future__ import annotations

import threading
import time
from collections import Counter
from typing import Any, Callable

from core.entry_freshness_audit import audit_5m_entry_freshness


def install(*, legacy: Any, kline_cache: dict, kline_cache_lock: threading.RLock, kline_cache_ttl: dict[str, float]) -> Callable[[], dict]:
    """Install diagnostic tracing and provide a hook for the active market-data manager."""
    if getattr(legacy, "_market_data_runtime_trace_installed", False):
        return legacy._market_data_runtime_trace_snapshot

    lock = threading.RLock()
    manager_lock = threading.RLock()
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
        "market_data_manager_bound": False,
        "market_data_manager_kline_calls": 0,
    }
    freshness_by_state: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    last_events: list[dict[str, Any]] = []
    manager_provenance: dict[tuple[str, str, int], dict[str, Any]] = {}

    original_fetch_klines = legacy.fetch_klines
    original_fetch_strategy_data = legacy.fetch_strategy_data
    original_score_symbol = legacy.score_symbol
    manager = None
    manager_wrapped = False

    def snapshot() -> dict[str, Any]:
        now = time.time()
        with lock:
            data = dict(stats)
            data["entry_freshness_by_state"] = dict(freshness_by_state)
            data["source_counts"] = dict(source_counts)
            data["last_events"] = list(last_events)
        data["captured_at"] = now
        return data

    def _manager_cache_snapshot(symbol: str, interval: str, limit: int):
        key = f"{interval}:{str(symbol).upper()}:{int(limit)}"
        if manager is None:
            return None, key
        try:
            return manager.cache.get(key), key
        except Exception:
            return None, key

    def _record_manager_kline(symbol: str, interval: str, limit: int, result: Any, before: Any, before_age: float | None):
        now = time.time()
        after, key = _manager_cache_snapshot(symbol, interval, limit)
        before_fetched_at = None
        after_fetched_at = None
        try:
            before_fetched_at = None if before is None else float(before.fetched_at)
        except (TypeError, ValueError):
            pass
        try:
            after_fetched_at = None if after is None else float(after.fetched_at)
        except (TypeError, ValueError):
            pass
        if before_fetched_at is None and after_fetched_at is not None:
            source = "REFRESHED"
        elif before_fetched_at is not None and after_fetched_at != before_fetched_at:
            source = "REFRESHED"
        elif after_fetched_at is not None:
            source = "CACHE_STALE" if (now - after_fetched_at) >= 310.0 else "CACHE"
        elif result:
            source = "FALLBACK_OR_UNTRACKED"
        else:
            source = "EMPTY"
        after_age = None if after_fetched_at is None else max(0.0, now - after_fetched_at)
        provenance = {
            "captured_at": now,
            "symbol": str(symbol).upper(),
            "interval": str(interval),
            "limit": int(limit),
            "manager_cache_key": key,
            "manager_cache_fetched_at": after_fetched_at,
            "manager_cache_age_seconds": None if after_age is None else round(after_age, 3),
            "manager_cache_age_before_seconds": None if before_age is None else round(before_age, 3),
            "source": source,
            "returned_rows": len(result) if isinstance(result, list) else None,
        }
        with manager_lock:
            manager_provenance[(str(symbol).upper(), str(interval), int(limit))] = provenance
        with lock:
            stats["market_data_manager_kline_calls"] += 1
            source_counts[source] += 1
            last_events.append({"event": "MANAGED_KLINE", "active_source": "MARKET_DATA_MANAGER", **provenance})
            del last_events[:-80]

    def traced_fetch_klines(symbol: str, interval: str, limit: int):
        key = (str(symbol).upper(), str(interval), int(limit))
        now = time.time()
        with kline_cache_lock:
            cached = kline_cache.get(key)
            cache_age = None if cached is None else max(0.0, now - cached[0])
            ttl = float(kline_cache_ttl.get(str(interval), 0.0))
            fresh = bool(cached is not None and cache_age is not None and cache_age < ttl)
        result = original_fetch_klines(symbol, interval, limit)
        with lock:
            stats["kline_calls"] += 1
            if fresh:
                stats["kline_hits"] += 1
            else:
                stats["kline_expired_or_missing"] += 1
            if not result:
                stats["kline_empty_returns"] += 1
            last_events.append({
                "event": "LEGACY_KLINE",
                "active_source": "LEGACY_FETCH_KLINES",
                "at": time.time(),
                "symbol": str(symbol).upper(),
                "interval": str(interval),
                "limit": int(limit),
                "cache_before": "HIT" if fresh else ("MISS" if cached is None else "EXPIRED"),
                "cache_age_before_seconds": None if cache_age is None else round(cache_age, 1),
                "ttl_seconds": ttl,
                "returned_rows": len(result) if isinstance(result, list) else None,
            })
            del last_events[:-80]
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
                    "[MARKET-DATA-TRACE] strategy_call=%d elapsed=%.3fs manager_calls=%d freshness=%s source_counts=%s",
                    summary["fetch_strategy_calls"],
                    summary["fetch_strategy_last_elapsed_seconds"] or 0.0,
                    summary["market_data_manager_kline_calls"],
                    summary["entry_freshness_by_state"],
                    summary["source_counts"],
                )

    def traced_score_symbol(symbol: str, ticker: dict, candles_15m: list[dict], candles_5m: list[dict]):
        result = original_score_symbol(symbol, ticker, candles_15m, candles_5m)
        symbol_key = str(symbol).upper()
        cache_key = (symbol_key, "5m", 60)
        with manager_lock:
            provenance = dict(manager_provenance.get(cache_key, {}))
        cache_timestamp = provenance.get("manager_cache_fetched_at")
        if cache_timestamp is None:
            with kline_cache_lock:
                cached = kline_cache.get(cache_key)
                cache_timestamp = None if cached is None else float(cached[0])
            cache_ttl = float(kline_cache_ttl.get("5m", 0.0))
        else:
            cache_ttl = 310.0
        audit = audit_5m_entry_freshness(
            candles_5m=candles_5m,
            captured_at=time.time(),
            cache_timestamp=cache_timestamp,
            cache_ttl_seconds=cache_ttl,
        )
        if provenance:
            audit["cache_source"] = provenance.get("source")
            audit["manager_cache_key"] = provenance.get("manager_cache_key")
            audit["manager_cache_fetched_at"] = provenance.get("manager_cache_fetched_at")
            audit["manager_cache_age_seconds"] = provenance.get("manager_cache_age_seconds")
            audit["provenance_captured_at"] = provenance.get("captured_at")
        if isinstance(result, dict):
            result["entry_freshness_5m"] = audit
        with lock:
            stats["entry_freshness_audits"] += 1
            freshness_by_state[str(audit.get("state", "UNKNOWN"))] += 1
            last_events.append({
                "event": "ENTRY_FRESHNESS_AUDIT",
                "at": time.time(),
                "symbol": symbol_key,
                "active_source": "MARKET_DATA_MANAGER" if provenance else "LEGACY_CACHE",
                "state": audit.get("state"),
                "decision_candle_open_time_ms": audit.get("decision_candle_open_time_ms"),
                "decision_candle_close_time_ms": audit.get("decision_candle_close_time_ms"),
                "decision_candle_age_seconds": audit.get("decision_candle_age_seconds"),
                "cache_age_seconds": audit.get("cache_age_seconds"),
                "manager_cache_age_seconds": audit.get("manager_cache_age_seconds"),
                "cache_expired": audit.get("cache_expired"),
                "cache_source": audit.get("cache_source"),
            })
            if isinstance(result, dict) and (
                int(result.get("scalp_score", 0) or 0) >= 50
                or int(result.get("score", 0) or 0) >= 65
            ):
                diagnostic = {
                    "event": "SCALP_GATE_DIAGNOSTIC",
                    "at": time.time(),
                    "symbol": symbol_key,
                    "score": result.get("score"),
                    "scalp_score": result.get("scalp_score"),
                    "swing_score": result.get("swing_score"),
                    "scalp_signal": result.get("scalp_signal"),
                    "trade_mode": result.get("trade_mode"),
                    "scalp_gate": result.get("scalp_gate"),
                    "scalp_gate_reasons": result.get("scalp_gate_reasons", []),
                    "scalp_confirmed_reversal": result.get("scalp_confirmed_reversal"),
                    "scalp_recovery_confirmation": result.get("scalp_recovery_confirmation"),
                    "scalp_recovery_trigger_count": result.get("scalp_recovery_trigger_count"),
                    "scalp_recovery_trigger_reasons": result.get("scalp_recovery_trigger_reasons", []),
                    "scalp_context_only": result.get("scalp_context_only"),
                    "volume_ratio_5m": result.get("volume_ratio_5m"),
                    "scalp_min_volume_ratio": result.get("scalp_min_volume_ratio"),
                    "rsi5m": result.get("rsi5m"),
                    "scalp_max_rsi": result.get("scalp_max_rsi"),
                    "pattern": result.get("pattern"),
                    "pattern_confirmed": result.get("pattern_confirmed"),
                    "mtf_countertrend_warning": result.get("mtf_countertrend_warning"),
                    "mtf_countertrend_veto": result.get("mtf_countertrend_veto"),
                    "mtf_aligned_bullish": result.get("mtf_aligned_bullish"),
                    "entry_freshness_state": audit.get("state"),
                    "manager_cache_age_seconds": audit.get("manager_cache_age_seconds"),
                    "cache_source": audit.get("cache_source"),
                }
                last_events.append(diagnostic)
                legacy.logger.info("[SCALP-GATE] %s", diagnostic)
            del last_events[:-120]
        return result

    def bind_market_data_manager(active_manager: Any) -> None:
        nonlocal manager, manager_wrapped
        with manager_lock:
            manager = active_manager
            if manager_wrapped:
                return
            active_fetch = legacy.fetch_klines
            if getattr(active_fetch, "_market_data_manager_runtime_wrapped", False):
                manager_wrapped = True
            else:
                def traced_managed_kline(symbol: str, interval: str, limit: int):
                    before, _ = _manager_cache_snapshot(symbol, interval, limit)
                    before_age = None
                    if before is not None:
                        try:
                            before_age = max(0.0, time.time() - float(before.fetched_at))
                        except (TypeError, ValueError):
                            before_age = None
                    result = active_fetch(symbol, interval, limit)
                    if str(interval) == "5m":
                        _record_manager_kline(symbol, interval, limit, result, before, before_age)
                    return result
                traced_managed_kline._market_data_manager_runtime_wrapped = True
                legacy.fetch_klines = traced_managed_kline
                manager_wrapped = True
            stats["market_data_manager_bound"] = True
            legacy.logger.info("[MARKET-DATA-TRACE] bound to active MarketDataManager managed_kline path")

    legacy.fetch_klines = traced_fetch_klines
    legacy.fetch_strategy_data = traced_fetch_strategy_data
    legacy.score_symbol = traced_score_symbol
    legacy._market_data_runtime_trace_bind_manager = bind_market_data_manager
    legacy._market_data_runtime_trace_installed = True
    legacy._market_data_runtime_trace_snapshot = snapshot
    return snapshot