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

    assert 'PAPER_VENUE_MODE == "BYBIT_ONLY_LAB"' in source
    assert 'row for row in ws_rows if row.get("is_closed")' in source
    assert 'manager.cache.put(' in source
    assert 'fetched_at=received_at' in source
    assert 'persist=False' in source


def test_binance_lab_path_remains_ws_only_for_cold_start():
    base = (ROOT / "shadow_main_base.py").read_text(encoding="utf-8")
    assert 'if PAPER_VENUE_MODE == "BINANCE_ONLY_LAB":' in base
    assert 'There is deliberately no REST' in base
    assert 'waiting_for_closed_ws_history' in base
