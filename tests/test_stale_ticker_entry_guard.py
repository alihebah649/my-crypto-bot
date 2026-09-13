import shadow_main


def test_stale_ticker_blocks_new_entry(monkeypatch):
    monkeypatch.setattr(shadow_main, "_ticker_cache_stale_active", True)
    monkeypatch.setattr(shadow_main, "_loss_cooldown", lambda symbol: 0.0)
    called = {"count": 0}

    def fake_open(symbol, entry_price, stop_loss, trade_mode):
        called["count"] += 1
        raise AssertionError("execution must not run with stale ticker")

    monkeypatch.setattr(shadow_main, "_original_runtime_open_position", fake_open)
    shadow_main.runtime.last_entry_diagnostics.clear()

    result = shadow_main._open_one_position("OPUSDT", 0.095, 0.094, "SCALP")

    assert result is None
    assert called["count"] == 0
    trace = shadow_main.runtime.last_entry_diagnostics["OPUSDT"]
    assert trace["result"] == "REJECTED_STALE_TICKER"
    assert trace["ticker_stale_active"] is True
    assert trace["execution"] == "NOT_RUN"


def test_fresh_ticker_does_not_trigger_stale_entry_guard(monkeypatch):
    monkeypatch.setattr(shadow_main, "_ticker_cache_stale_active", False)
    monkeypatch.setattr(shadow_main, "_loss_cooldown", lambda symbol: 0.0)
    called = {"count": 0}

    class _Position:
        entry_metadata = {"trade_mode": "SCALP"}
        metadata = {"trade_mode": "SCALP"}

    def fake_open(symbol, entry_price, stop_loss, trade_mode):
        called["count"] += 1
        return _Position()

    class _Repo:
        def update(self, position):
            pass

    monkeypatch.setattr(shadow_main, "_original_runtime_open_position", fake_open)
    monkeypatch.setattr(shadow_main.runtime, "repository", _Repo())

    result = shadow_main._open_one_position("OPUSDT", 0.095, 0.094, "SCALP")

    assert result is not None
    assert called["count"] == 1
