def test_runtime_scalp_diagnostics_schema():
    diagnostic = {
        "scalp_score": 69,
        "scalp_gate": False,
        "scalp_gate_reasons": ["5M_VOLUME_TOO_LOW"],
    }
    assert diagnostic["scalp_score"] >= 65
    assert diagnostic["scalp_gate"] is False
    assert diagnostic["scalp_gate_reasons"]
