from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_shadow_main_embedded_base_does_not_start_before_overlays():
    base_source = (ROOT / "shadow_main_base.py").read_text(encoding="utf-8")
    main_source = (ROOT / "shadow_main.py").read_text(encoding="utf-8")

    assert 'if __name__ == "__main__" and not globals().get("_SHADOW_MAIN_EMBEDDED", False):' in base_source
    assert 'globals()["_SHADOW_MAIN_EMBEDDED"] = True' in main_source
    assert 'globals().pop("_SHADOW_MAIN_EMBEDDED", None)' in main_source
