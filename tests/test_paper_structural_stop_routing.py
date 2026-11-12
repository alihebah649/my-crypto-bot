from core.paper_structural_stop_routing import resolve_structural_stop_stream


def test_restored_main_mode_resolves_to_binance_relay_stream():
    stream = object()

    venue, selected, report_mode = resolve_structural_stop_stream(
        "MAIN",
        "MIXED",
        {"_binance_market_stream": stream},
    )

    assert venue == "BINANCE"
    assert selected is stream
    assert report_mode == "MAIN"


def test_mixed_mode_and_unknown_modes_keep_safe_routing():
    stream = object()

    assert resolve_structural_stop_stream(
        "MIXED", "UNKNOWN", {"_binance_market_stream": stream}
    ) == ("BINANCE", stream, "MAIN")
    assert resolve_structural_stop_stream("MISSING", "MIXED", {}) == (
        "UNKNOWN", None, "MISSING"
    )
