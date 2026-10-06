from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_bybit_lab_syncs_live_ws_5m_into_manager_without_persisting_each_cycle():
    base = (ROOT / "shadow_main_base.py").read_text(encoding="utf-8")
    tree = ast.parse(base)
    source = ast.get_source_segment(base, next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_guarded_fetch_klines"
    )) or ""

    assert 'def _sync_bybit_ws_kline_manager_cache' in base
    assert 'PAPER_VENUE_MODE == "BYBIT_ONLY_LAB"' in base
    assert 'row for row in ws_rows if row.get("is_closed")' in base
    assert 'event_stream_healthy' in base
    assert 'fetched_at=time.time()' in base
    assert 'persist=False' in base
    assert 'live_age = max(0.0, time.time() - received_at)' not in base
    assert base.count('_sync_bybit_ws_kline_manager_cache(manager, cache_key, ws_rows, stream)') >= 3


def test_binance_lab_path_remains_ws_only_for_cold_start():
    base = (ROOT / "shadow_main_base.py").read_text(encoding="utf-8")
    assert 'if PAPER_VENUE_MODE == "BINANCE_ONLY_LAB":' in base
    assert 'There is deliberately no REST' in base
    assert 'waiting_for_closed_ws_history' in base
