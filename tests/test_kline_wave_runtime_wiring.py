from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_paper_runtime_activates_kline_wave_scheduler():
    base = (ROOT / "shadow_main_base.py").read_text(encoding="utf-8")
    assert "from core.market_data_manager import MarketDataManager, PersistentMarketDataCache" in base
    assert "_market_data_manager = MarketDataManager(" in base
    assert "_legacy.market_data_manager = _market_data_manager" in base
    assert "kline_wave_count=3" in base
    assert "kline_wave_interval_seconds=30.0" in base
    assert "ticker_group_interval_seconds=30.0" in base


def test_runtime_trace_is_bound_to_the_active_kline_manager():
    main = (ROOT / "shadow_main.py").read_text(encoding="utf-8")
    assert '_legacy._market_data_runtime_trace_bind_manager(_active_market_data_manager)' in main


def test_kline_fetch_syncs_the_manager_cache_and_hydrates_memory():
    base = (ROOT / "shadow_main_base.py").read_text(encoding="utf-8")
    assert 'manager.cache.put(' in base
    assert 'f"{str(interval)}:{str(symbol).upper()}:{int(limit)}"' in base
    assert 'manager_cache = manager.cache.get(' in base
    assert '_kline_cache[key] = (float(manager_cache.fetched_at), payload)' in base


def test_runtime_merges_staggered_ticker_groups_into_full_snapshot():
    main = (ROOT / "shadow_main.py").read_text(encoding="utf-8")
    assert "manager.refresh_ticker_group(_fetch_ticker_group_from_binance, now=now)" in main
    assert "data = manager.merged_ticker_snapshot()" in main
    assert "_TICKER_CACHE_TTL = 30.0" in main


def test_core_bootstrap_does_not_compete_with_explicit_shadow_manager():
    core_init = (ROOT / "core" / "__init__.py").read_text(encoding="utf-8")
    main = (ROOT / "shadow_main.py").read_text(encoding="utf-8")
    base = (ROOT / "shadow_main_base.py").read_text(encoding="utf-8")
    assert '_SHADOW_MAIN_MANAGES_MARKET_DATA' in core_init
    assert 'getattr(main, "_SHADOW_MAIN_MANAGES_MARKET_DATA", False)' in core_init
    assert 'globals()["_SHADOW_MAIN_MANAGES_MARKET_DATA"] = True' in main
    assert '_legacy._market_data_manager_installed = True' in base
    assert "ticker_group_interval_seconds=30.0" in core_init
