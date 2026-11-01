from __future__ import annotations

import json
import time

import pytest

from core.hosted_paper_labs import HostedPaperLabRunner


class FakeResult:
    def __init__(self, rowcount=0, rows=None):
        self.rowcount = rowcount
        self.rows = list(rows or [])

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)


class FakeDatabase:
    def __init__(self):
        self.rows = {}


class FakeConnection:
    def __init__(self, database):
        self.database = database
        self.closed = False

    def execute(self, sql, params=()):
        normalized = " ".join(str(sql).split()).upper()
        if normalized.startswith("CREATE TABLE") or normalized.startswith("CREATE INDEX"):
            return FakeResult()
        if normalized.startswith("INSERT INTO PAPER_EVIDENCE"):
            evidence_type, identity_key, payload = params
            key = (evidence_type, identity_key)
            if key in self.database.rows and "DO UPDATE" not in normalized:
                return FakeResult(rowcount=0)
            self.database.rows[key] = json.loads(payload)
            return FakeResult(rowcount=1)
        if normalized.startswith("SELECT PAYLOAD"):
            evidence_type = params[0]
            return FakeResult(rows=[
                (payload,)
                for (kind, _), payload in self.database.rows.items()
                if kind == evidence_type
            ])
        if normalized.startswith("SELECT COUNT(*)"):
            evidence_type = params[0]
            return FakeResult(rows=[(
                sum(1 for kind, _ in self.database.rows if kind == evidence_type),
            )])
        if normalized.startswith("DELETE FROM PAPER_EVIDENCE"):
            evidence_type = params[0]
            limit = int(params[1])
            keys = [key for key in self.database.rows if key[0] == evidence_type][:limit]
            for key in keys:
                self.database.rows.pop(key, None)
            return FakeResult()
        raise AssertionError(f"Unhandled SQL: {normalized}")

    def commit(self):
        return None

    def close(self):
        self.closed = True


class FakeStream:
    def __init__(self, venue, symbols):
        self.venue = venue
        self.symbols = tuple(symbols)
        self.started = False
        self.prices = {
            symbol: 100.0 + (10.0 if venue == "OKX" else 5.0 if venue == "BYBIT" else 0.0)
            for symbol in symbols
        }

    def start(self):
        self.started = True

    def stop(self):
        self.started = False

    def snapshot(self, now=None):
        return {
            "available": True,
            "connected": True,
            "event_stream_healthy": True,
            "tickers_with_latest": len(self.prices),
            "coverage_kline_percent": 100.0,
            "last_error": None,
        }

    def get_latest_ticker(self, symbol):
        price = self.prices.get(symbol.upper())
        if price is None:
            return None
        now = time.time()
        return {
            "symbol": symbol.upper(),
            "lastPrice": price,
            "bidPrice": price * 0.9999,
            "askPrice": price * 1.0001,
            "quoteVolume": 1_000_000.0,
            "received_at": now,
            "market_data_source": self.venue,
        }

    def get_kline_history(self, symbol, interval, limit):
        return []

    def seed_kline_history(self, symbol, interval, rows):
        return len(list(rows))


def _runner(database):
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT"]
    return HostedPaperLabRunner(
        symbols=symbols,
        binance_stream=FakeStream("BINANCE", symbols),
        bybit_stream=FakeStream("BYBIT", symbols),
        okx_stream=FakeStream("OKX", symbols),
        database_url="postgres://test",
        initial_cash=1000.0,
        fee_rate=0.001,
        scan_batch_size=2,
        connect_factory=lambda _url: FakeConnection(database),
    )


def test_hosted_runner_creates_three_isolated_paper_accounts_and_state_namespaces():
    database = FakeDatabase()
    runner = _runner(database)

    assert runner.enabled is True
    assert set(runner.labs) == {"BINANCE", "BYBIT", "OKX"}
    assert len({id(lab.runtime) for lab in runner.labs.values()}) == 3
    assert len({id(lab.adapter) for lab in runner.labs.values()}) == 3
    assert len({id(lab.repository) for lab in runner.labs.values()}) == 3
    assert {
        evidence_type
        for evidence_type, _identity in database.rows
        if evidence_type.startswith("PAPER_LAB_STATE_")
    } == {
        "PAPER_LAB_STATE_BINANCE",
        "PAPER_LAB_STATE_BYBIT",
        "PAPER_LAB_STATE_OKX",
    }

    runner.close()


def test_hosted_lab_state_restores_each_venue_cash_without_cross_contamination():
    database = FakeDatabase()
    first = _runner(database)
    first.labs["BINANCE"].adapter.balance.cash = 925.0
    first.labs["BYBIT"].adapter.balance.cash = 850.0
    first.labs["OKX"].adapter.balance.cash = 775.0
    for lab in first.labs.values():
        lab._save_state(force=True)
    first.close()

    second = _runner(database)
    assert second.labs["BINANCE"].adapter.balance.cash == pytest.approx(925.0)
    assert second.labs["BYBIT"].adapter.balance.cash == pytest.approx(850.0)
    assert second.labs["OKX"].adapter.balance.cash == pytest.approx(775.0)
    second.close()


def test_hosted_labs_update_positions_from_their_own_exchange_prices():
    database = FakeDatabase()
    runner = _runner(database)
    try:
        for venue, lab in runner.labs.items():
            price = {"BINANCE": 100.0, "BYBIT": 105.0, "OKX": 110.0}[venue]
            lab.runtime.update_market(
                "BTCUSDT",
                price=price,
                bid=price * 0.9999,
                ask=price * 1.0001,
                spread_percent=0.02,
                atr=1.0,
                volume_usdt=1_000_000.0,
                ema100=price * 0.95,
            )
            position = lab.runtime.open_position(
                "BTCUSDT", price, price - 5.0, trade_mode="SCALP"
            )
            assert position is not None
            lab.stream.prices["BTCUSDT"] = price + 1.0

        for lab in runner.labs.values():
            lab._update_positions(time.time())

        assert runner.labs["BINANCE"].runtime.market.price["BTCUSDT"] == pytest.approx(101.0)
        assert runner.labs["BYBIT"].runtime.market.price["BTCUSDT"] == pytest.approx(106.0)
        assert runner.labs["OKX"].runtime.market.price["BTCUSDT"] == pytest.approx(111.0)
    finally:
        runner.close()


def test_resource_guard_pauses_new_entries_without_stopping_existing_streams():
    database = FakeDatabase()
    runner = _runner(database)
    try:
        runner._max_memory_mb = 405.0
        runner.process_cycle()
        assert all(lab.pause_new_entries for lab in runner.labs.values())
        assert runner.snapshot()["memory_guard"] is True
        assert all(lab.stream.started is False for lab in runner.labs.values())
    finally:
        runner.close()
