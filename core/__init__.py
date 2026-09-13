"""Core package bootstrap.

Paper Trading only: when the legacy market module is already loaded, install the
persistent market-data layer before shadow_main captures its network callables.
"""
from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

from .market_data_manager import MarketDataManager, PersistentMarketDataCache


def _shadow_main_module():
    for module in list(sys.modules.values()):
        path = getattr(module, "__file__", "") or ""
        if path.endswith("shadow_main.py"):
            return module
    return None


def _install_market_data_layer() -> None:
    legacy = sys.modules.get("shadow_main_legacy")
    if legacy is None or getattr(legacy, "_market_data_manager_installed", False):
        return

    state_dir = Path(getattr(legacy, "PAPER_STATE_DIR", "data/paper"))
    manager = MarketDataManager(
        PersistentMarketDataCache(state_dir / "market_data_cache.json"),
        ticker_symbols=getattr(legacy, "TRADING_SYMBOLS", []),
        ticker_batch_size=11,
        ticker_group_interval_seconds=30.0,
    )

    original_ticker: Callable[[], dict[str, Any]] = legacy.fetch_24h_tickers
    original_kline: Callable[[str, str, int], list[dict]] = legacy.fetch_klines

    def fetch_ticker_batch(batch: list[str]) -> dict[str, Any]:
        symbols_json = json.dumps(batch, separators=(",", ":"))
        raw = legacy._binance_get("/api/v3/ticker/24hr", {"symbols": symbols_json})
        return {
            str(item.get("symbol")): item
            for item in raw
            if item.get("symbol") in batch
        }

    def managed_tickers() -> dict[str, Any]:
        try:
            manager.refresh_ticker_group(fetch_ticker_batch)
        except Exception as exc:
            main = _shadow_main_module()
            set_block = getattr(main, "_set_binance_block", None) if main is not None else None
            if set_block is not None:
                try:
                    set_block(exc, "/api/v3/ticker/24hr")
                except Exception:
                    pass
        snapshot = manager.merged_ticker_snapshot()
        main = _shadow_main_module()
        if main is not None:
            lock = getattr(main, "_ticker_cache_lock", threading.RLock())
            with lock:
                if hasattr(main, "_ticker_cache"):
                    main._ticker_cache = (time.time(), dict(snapshot))
        return snapshot

    def managed_kline(symbol: str, interval: str, limit: int):
        key = f"{interval}:{str(symbol).upper()}:{int(limit)}"
        cached = manager.get_for_analysis(interval, key)
        if cached is not None:
            return cached.payload
        main = _shadow_main_module()
        if main is not None and getattr(main, "_binance_guard_active", lambda: False)():
            return []
        try:
            data = original_kline(symbol, interval, limit)
            if data:
                manager.cache.put(key, data)
            return data
        except Exception as exc:
            set_block = getattr(main, "_set_binance_block", None) if main is not None else None
            if set_block is not None:
                try:
                    set_block(exc, f"/api/v3/klines:{symbol}:{interval}")
                except Exception:
                    pass
            return cached.payload if cached is not None else []

    original_open = getattr(legacy.runtime, "open_position", None)

    def freshness_checked_open_position(symbol: str, *args, **kwargs):
        symbol_key = str(symbol).upper()
        required = (
            ("ticker", f"ticker:{symbol_key}"),
            ("5m", f"5m:{symbol_key}:60"),
            ("15m", f"15m:{symbol_key}:150"),
        )
        for dataset, key in required:
            if not manager.entry_data_is_fresh(dataset, key):
                return None
        if original_open is None:
            return None
        return original_open(symbol, *args, **kwargs)

    legacy.fetch_24h_tickers = managed_tickers
    legacy.fetch_klines = managed_kline
    if original_open is not None:
        legacy.runtime.open_position = freshness_checked_open_position

    legacy.market_data_manager = manager
    legacy._market_data_manager_installed = True

    def ticker_refresh_loop() -> None:
        while True:
            try:
                managed_tickers()
            except Exception:
                try:
                    legacy.logger.exception("Persistent ticker refresh failed")
                except Exception:
                    pass
            time.sleep(30.0)

    threading.Thread(target=ticker_refresh_loop, daemon=True, name="persistent-market-data").start()


_install_market_data_layer()
