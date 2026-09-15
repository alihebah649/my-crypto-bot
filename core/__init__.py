"""Core package bootstrap.

The Paper market-data layer is installed asynchronously after the legacy
application module has finished importing.  This avoids touching partially
initialized modules during the import graph while keeping the integration
automatic.
"""
from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path
from typing import Any


def _find_legacy():
    return sys.modules.get("shadow_main_legacy")


def _find_shadow_main():
    for module in list(sys.modules.values()):
        if str(getattr(module, "__file__", "")).endswith("shadow_main.py"):
            return module
    return None


def _start_score_snapshot_monitor(legacy: Any) -> None:
    """Log the highest completed score snapshots for SCALP diagnosis.

    This is diagnostic-only and reads in-memory state populated by the active
    market cycle. It performs no Binance/API requests and does not modify any
    strategy, gate, risk, Trade Manager, or execution decision. Recording the
    top snapshots regardless of score is intentional: a sub-65 scalp score is
    precisely where we need to see which component is preventing entry.
    """
    if getattr(legacy, "_scalp_score_snapshot_monitor_started", False):
        return
    legacy._scalp_score_snapshot_monitor_started = True
    last_fingerprint = None

    def monitor() -> None:
        nonlocal last_fingerprint
        while True:
            try:
                latest = getattr(legacy, "latest_scores", {}) or {}
                candidates = []
                for symbol, result in latest.items():
                    if not isinstance(result, dict):
                        continue
                    selected_score = int(result.get("score", 0) or 0)
                    scalp_score = int(result.get("scalp_score", 0) or 0)
                    candidates.append({
                        "symbol": str(symbol).upper(),
                        "score": selected_score,
                        "scalp_score": scalp_score,
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
                        "entry_freshness_5m": result.get("entry_freshness_5m"),
                    })
                candidates.sort(key=lambda row: (row["scalp_score"], row["score"], row["symbol"]), reverse=True)
                top_candidates = candidates[:12]
                if top_candidates:
                    fingerprint = tuple(
                        (
                            row["symbol"], row["score"], row["scalp_score"],
                            row["scalp_signal"], row["scalp_gate"],
                            tuple(row["scalp_gate_reasons"] or []),
                        )
                        for row in top_candidates
                    )
                    if fingerprint != last_fingerprint:
                        last_fingerprint = fingerprint
                        legacy.logger.info(
                            "[SCALP-SNAPSHOT] %s",
                            {"count": len(candidates), "top": top_candidates},
                        )
            except Exception:
                try:
                    legacy.logger.exception("SCALP score snapshot monitor failed")
                except Exception:
                    pass
            time.sleep(5.0)

    threading.Thread(target=monitor, daemon=True, name="scalp-score-snapshot").start()


def _install_market_data_layer() -> bool:
    try:
        legacy = _find_legacy()
        if legacy is None or getattr(legacy, "_market_data_manager_installed", False):
            return False

        ticker = getattr(legacy, "fetch_24h_tickers", None)
        kline = getattr(legacy, "fetch_klines", None)
        symbols = list(getattr(legacy, "TRADING_SYMBOLS", []) or [])
        if not callable(ticker) or not callable(kline) or not symbols:
            return False

        from .market_data_manager import MarketDataManager, PersistentMarketDataCache

        state_dir = Path(getattr(legacy, "PAPER_STATE_DIR", "data/paper"))
        manager = MarketDataManager(
            PersistentMarketDataCache(state_dir / "market_data_cache.json"),
            ticker_symbols=symbols,
            ticker_batch_size=11,
            ticker_group_interval_seconds=65.0,
        )

        original_ticker = ticker
        original_kline = kline

        def fetch_ticker_batch(batch: list[str]) -> dict[str, Any]:
            symbols_json = json.dumps(batch, separators=(",", ":"))
            raw = legacy._binance_get("/api/v3/ticker/24hr", {"symbols": symbols_json})
            if not isinstance(raw, list):
                return {}
            return {
                str(item.get("symbol")): item
                for item in raw
                if isinstance(item, dict) and item.get("symbol") in batch
            }

        def managed_tickers() -> dict[str, Any]:
            refresh_succeeded = False
            try:
                fetched = manager.refresh_ticker_group(fetch_ticker_batch)
                refresh_succeeded = bool(fetched)
            except Exception as exc:
                main = _find_shadow_main()
                set_block = getattr(main, "_set_binance_block", None) if main is not None else None
                if callable(set_block):
                    try:
                        set_block(exc, "/api/v3/ticker/24hr")
                    except Exception:
                        pass
            snapshot = manager.merged_ticker_snapshot()
            main = _find_shadow_main()
            if main is not None and hasattr(main, "_ticker_cache_lock"):
                try:
                    timestamps = []
                    for symbol in manager.symbols:
                        item = manager.cache.get(f"ticker:{symbol}")
                        if item is None:
                            timestamps = []
                            break
                        timestamps.append(item.fetched_at)
                    oldest_fetched_at = min(timestamps) if timestamps else 0.0
                    with main._ticker_cache_lock:
                        main._ticker_cache = (oldest_fetched_at, dict(snapshot))
                        main._ticker_cache_stale_active = not refresh_succeeded and not timestamps
                        if timestamps:
                            now = time.time()
                            main._ticker_cache_stale_active = (now - oldest_fetched_at) >= 75.0
                except Exception:
                    pass
            return snapshot

        def managed_kline(symbol: str, interval: str, limit: int):
            key = f"{interval}:{str(symbol).upper()}:{int(limit)}"
            cached = manager.get_for_analysis(interval, key)
            if cached is not None and manager.entry_data_is_fresh(interval, key):
                return cached.payload
            main = _find_shadow_main()
            if main is not None and callable(getattr(main, "_binance_guard_active", None)):
                try:
                    if main._binance_guard_active():
                        return []
                except Exception:
                    pass
            try:
                data = original_kline(symbol, interval, limit)
                if data:
                    manager.cache.put(key, data)
                return data
            except Exception:
                return cached.payload if cached is not None else []

        legacy.fetch_24h_tickers = managed_tickers
        legacy.fetch_klines = managed_kline
        legacy.market_data_manager = manager
        legacy._market_data_manager_installed = True
        legacy._market_data_manager_original_ticker = original_ticker
        legacy._market_data_manager_original_kline = original_kline

        bind_trace = getattr(legacy, "_market_data_runtime_trace_bind_manager", None)
        if callable(bind_trace):
            try:
                bind_trace(manager)
            except Exception:
                legacy.logger.exception("Market-data runtime trace manager binding failed")

        _start_score_snapshot_monitor(legacy)

        def refresh_loop() -> None:
            while True:
                try:
                    managed_tickers()
                except Exception:
                    try:
                        legacy.logger.exception("Persistent ticker refresh failed")
                    except Exception:
                        pass
                time.sleep(30.0)

        threading.Thread(target=refresh_loop, daemon=True, name="persistent-market-data").start()
        try:
            legacy.logger.info("Persistent market-data layer installed: 11+11 ticker groups, 65s inter-group gap")
        except Exception:
            pass
        return True
    except Exception:
        return False


def _delayed_install() -> None:
    for _ in range(20):
        if _install_market_data_layer():
            return
        if getattr(_find_legacy(), "_market_data_manager_installed", False):
            return
        time.sleep(1.0)


threading.Thread(target=_delayed_install, daemon=True, name="market-data-bootstrap").start()
