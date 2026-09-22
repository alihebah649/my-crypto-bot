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


def test_runtime_trace_is_bound_to_the_active_kline_manager():
    main = (ROOT / "shadow_main.py").read_text(encoding="utf-8")
    assert '_legacy._market_data_runtime_trace_bind_manager(_active_market_data_manager)' in main
