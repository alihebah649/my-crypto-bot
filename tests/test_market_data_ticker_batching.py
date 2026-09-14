import importlib
import json


def test_fetch_24h_tickers_batches_symbols_at_twenty(monkeypatch):
    # Other modules in the same process intentionally wrap the legacy fetcher
    # during integration imports. Reload this module so this unit test exercises
    # the actual legacy implementation in isolation.
    shadow_main_legacy = importlib.import_module("shadow_main_legacy")
    shadow_main_legacy = importlib.reload(shadow_main_legacy)

    symbols = [f"S{i:02d}USDT" for i in range(22)]
    calls = []

    monkeypatch.setattr(shadow_main_legacy, "TRADING_SYMBOLS", symbols)

    def fake_get(path, params=None, timeout=12.0):
        calls.append((path, params))
        requested = json.loads(params["symbols"])
        return [{"symbol": symbol, "lastPrice": "1"} for symbol in requested]

    monkeypatch.setattr(shadow_main_legacy, "_binance_get", fake_get)

    result = shadow_main_legacy.fetch_24h_tickers()

    assert list(result) == symbols
    assert len(calls) == 2
    batches = [json.loads(params["symbols"]) for _, params in calls]
    assert [len(batch) for batch in batches] == [20, 2]
    assert all(len(batch) <= 20 for batch in batches)
