from __future__ import annotations

from core.trade_history_store import TradeHistoryRecord, TradeHistoryStore


class FakeBinanceClient:
    def __init__(self):
        self.calls = []

    def get_my_trades(self, *, symbol, limit):
        self.calls.append((symbol, limit))
        return [
            {
                "id": 123,
                "symbol": symbol,
                "orderId": 456,
                "price": "100.5",
                "qty": "0.5",
                "quoteQty": "50.25",
                "commission": "0.05025",
                "commissionAsset": "USDT",
                "time": 1750000000000,
                "isBuyer": True,
                "isMaker": False,
            }
        ]


def test_upsert_keeps_single_record_per_trade_id(tmp_path):
    store = TradeHistoryStore(tmp_path / "trade_history.json")
    store.upsert(TradeHistoryRecord(trade_id="1", symbol="BTCUSDT", source="PAPER", side="BUY"))
    store.upsert(TradeHistoryRecord(trade_id="1", symbol="BTCUSDT", source="PAPER", side="BUY", price=101.0))

    records = store.all()
    assert len(records) == 1
    assert records[0]["price"] == 101.0


def test_sync_binance_trades_normalizes_and_persists(tmp_path):
    store = TradeHistoryStore(tmp_path / "trade_history.json")
    client = FakeBinanceClient()

    count = store.sync_binance_trades(client, ["BTCUSDT"], source="LIVE")

    assert count == 1
    record = store.all()[0]
    assert record["trade_id"] == "123"
    assert record["symbol"] == "BTCUSDT"
    assert record["source"] == "LIVE"
    assert record["side"] == "BUY"
    assert record["order_id"] == "456"
    assert record["price"] == 100.5
    assert record["quantity"] == 0.5
    assert record["commission"] == 0.05025
    assert record["commission_asset"] == "USDT"
