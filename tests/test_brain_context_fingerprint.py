from core.brain_context_fingerprint import brain_context_fingerprint


def test_fingerprint_is_order_independent():
    a = {"symbol": "BTCUSDT", "risk": {"locked": False, "score": 2}}
    b = {"risk": {"score": 2, "locked": False}, "symbol": "BTCUSDT"}
    assert brain_context_fingerprint(a) == brain_context_fingerprint(b)


def test_fingerprint_changes_when_context_changes():
    a = {"symbol": "BTCUSDT", "pnl_percent": 1.0}
    b = {"symbol": "BTCUSDT", "pnl_percent": 1.1}
    assert brain_context_fingerprint(a) != brain_context_fingerprint(b)
