from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_shadow_main_embedded_base_does_not_start_before_overlays():
    base_source = (ROOT / "shadow_main_base.py").read_text(encoding="utf-8")
    main_source = (ROOT / "shadow_main.py").read_text(encoding="utf-8")

    assert 'if __name__ == "__main__" and not globals().get("_SHADOW_MAIN_EMBEDDED", False):' in base_source
    assert 'globals()["_SHADOW_MAIN_EMBEDDED"] = True' in main_source
    assert 'globals().pop("_SHADOW_MAIN_EMBEDDED", None)' in main_source


def test_main_structural_stop_comparison_resolves_to_binance_stream_after_restore():
    source = (ROOT / "shadow_main.py").read_text(encoding="utf-8")
    module = ast.parse(source)
    assignment = next(
        node for node in module.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name)
            and target.id == "_PAPER_STRUCTURAL_STOP_COMPARISON_VENUES"
            for target in node.targets
        )
    )

    venues = ast.literal_eval(assignment.value)
    assert venues["MAIN"] == ("BINANCE", "_binance_market_stream", "MAIN")
    assert venues["MIXED"] == venues["MAIN"]


def test_precalibration_shadow_initializes_risk_before_first_preflight_read():
    source = (ROOT / "shadow_main.py").read_text(encoding="utf-8")
    module = ast.parse(source)
    function = next(
        node for node in module.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "_record_precalibration_shadow_candidates"
    )

    assignment_lines = [
        node.lineno
        for node in ast.walk(function)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "risk"
            for target in node.targets
        )
    ]
    load_lines = [
        node.lineno
        for node in ast.walk(function)
        if isinstance(node, ast.Name)
        and node.id == "risk"
        and isinstance(node.ctx, ast.Load)
    ]

    assert assignment_lines
    assert load_lines
    assert min(assignment_lines) < min(load_lines)
