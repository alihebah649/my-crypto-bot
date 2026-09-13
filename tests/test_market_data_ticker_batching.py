import shadow_main_legacy


def test_fetch_24h_tickers_batches_symbols_at_twenty(monkeypatch):
    symbols = [f"S{i:02d}USDT" for i in range(22)]
    calls = []

    monkeypatch.setattr(shadow_main_legacy, "TRADING_SYMBOLS", symbols)

    def fake_get(path, params=None, timeout=12.0):
        calls.append((path, params))
        requested = __import__("json").loads(params["symbols"])
        return [{"symbol": symbol, "lastPrice": "1"} for symbol in requested]

    monkeypatch.setattr(shadow_main_legacy, "_binance_get", fake_get)

    result = shadow_main_legacy.fetch_24h_tickers()

    assert list(result) == symbols
    assert len(calls) == 2
    batches = [__import__("json").loads(params["symbols"]) for _, params in calls]
    assert [len(batch) for batch in batches] == [20, 2]
    assert all(len(batch) <= 20 for batch in batches)
