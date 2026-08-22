from __future__ import annotations

import inspect

import shadow_main


def test_paper_entrypoint_does_not_submit_live_orders():
    source = inspect.getsource(shadow_main)
    forbidden = (
        "create_order(",
        "order_market_buy(",
        "order_market_sell(",
        "new_order(",
    )
    assert not any(token in source for token in forbidden)
    assert "PAPER" in source


def test_paper_runtime_uses_paper_execution_adapter():
    adapter_name = type(shadow_main.runtime.execution_adapter).__name__
    assert adapter_name == "PaperExecutionAdapter"


def test_paper_mode_is_explicit():
    assert getattr(shadow_main.app, "name", None)
    assert shadow_main.runtime.execution_adapter.__class__.__name__ == "PaperExecutionAdapter"
