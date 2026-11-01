from __future__ import annotations

import json
import time
from types import SimpleNamespace

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
    # MAIN already owns and has started this shared Binance stream.
    binance_stream = FakeStream("BINANCE", symbols)
    binance_stream.start()
    return HostedPaperLabRunner(
        symbols=symbols,
        binance_stream=binance_stream,
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
        runner.start()
        runner._max_memory_mb = 405.0
        runner.process_cycle()
        assert all(lab.pause_new_entries for lab in runner.labs.values())
        assert runner.snapshot()["memory_guard"] is True
        assert all(lab.stream.started is True for lab in runner.labs.values())
    finally:
        runner.close()



def test_hosted_runner_scans_every_venue_each_main_cycle():
    database = FakeDatabase()
    runner = _runner(database)
    try:
        runner.process_cycle()
        assert all(lab.scan_cursor == 2 for lab in runner.labs.values())

        runner.process_cycle()
        assert all(lab.scan_cursor == 0 for lab in runner.labs.values())

        runner.process_cycle()
        assert all(lab.scan_cursor == 2 for lab in runner.labs.values())
        assert runner.snapshot()["entry_scan_venues"] == ["BINANCE", "BYBIT", "OKX"]
    finally:
        runner.close()


def test_hosted_lab_does_not_run_exit_watchdog_with_stale_position_prices(monkeypatch):
    database = FakeDatabase()
    runner = _runner(database)
    lab = runner.labs["BYBIT"]
    try:
        lab.runtime.update_market(
            "BTCUSDT",
            price=100.0,
            bid=99.99,
            ask=100.01,
            spread_percent=0.02,
            atr=1.0,
            volume_usdt=1_000_000.0,
            ema100=90.0,
        )
        position = lab.runtime.open_position(
            "BTCUSDT", 100.0, 95.0, trade_mode="SCALP"
        )
        assert position is not None

        lab.stream.prices.pop("BTCUSDT", None)

        def forbidden_watchdog():
            pytest.fail("Exit watchdog must not act on a stale venue mark price")

        monkeypatch.setattr(lab.runtime, "run_exit_watchdog", forbidden_watchdog)
        lab._update_positions(time.time())

        assert lab.repository.get(position.position_id).status.name == "OPEN"
        assert lab.entry_blocked["EXIT_WATCHDOG_VENUE_PRICE_STALE"] == 1
    finally:
        runner.close()



def test_startup_memory_guard_disables_labs_before_opening_streams(monkeypatch):
    database = FakeDatabase()
    monkeypatch.setattr(
        HostedPaperLabRunner,
        "_memory_mb",
        staticmethod(lambda: 405.0),
    )
    runner = _runner(database)

    assert runner.enabled is False
    assert "startup memory guard" in runner.start_error
    assert runner.labs == {}
    assert runner.snapshot()["memory_guard"] is True



def test_hosted_lane_context_does_not_reuse_the_other_lanes_score():
    from core.hosted_paper_labs import _lane_context_missing

    swing_only = {
        "trade_mode": "SWING",
        "signal": "BUY",
        "score": 95,
        "swing_score": 95,
        "swing_signal": "BUY",
        "scalp_signal": "BUY",
        "scalp_confirmed_reversal": True,
    }
    scalp_only = {
        "trade_mode": "SCALP",
        "signal": "BUY",
        "score": 95,
        "scalp_score": 95,
        "scalp_signal": "BUY",
        "swing_signal": "BUY",
    }

    assert _lane_context_missing(swing_only, "SCALP") == ["scalp_score"]
    assert _lane_context_missing(scalp_only, "SWING") == ["swing_score"]


def test_hosted_scalp_lane_requires_reversal_or_recovery_context_field():
    from core.hosted_paper_labs import _lane_context_missing

    score = {
        "trade_mode": "SCALP",
        "score": 70,
        "scalp_score": 70,
        "scalp_signal": "BUY",
        "swing_score": 35,
        "swing_signal": "HOLD",
    }
    assert _lane_context_missing(score, "SCALP") == [
        "scalp_reversal_or_recovery_confirmation"
    ]


def test_hosted_lane_context_accepts_complete_independent_lanes():
    from core.hosted_paper_labs import _lane_context_missing

    scalp = {
        "trade_mode": "SCALP",
        "score": 70,
        "scalp_score": 70,
        "scalp_signal": "BUY",
        "scalp_confirmed_reversal": False,
        "scalp_recovery_confirmation": True,
    }
    swing = {
        "trade_mode": "SWING",
        "score": 82,
        "swing_score": 82,
        "swing_signal": "BUY",
    }
    assert _lane_context_missing(scalp, "SCALP") == []
    assert _lane_context_missing(swing, "SWING") == []



def test_hosted_lab_persists_entry_v2_candidate_with_all_gate_results():
    database = FakeDatabase()
    runner = _runner(database)
    lab = runner.labs["BYBIT"]
    try:
        capture = SimpleNamespace(
            capture_id="bybit-entry-capture-1",
            symbol="BTCUSDT",
            to_dict=lambda: {
                "schema_version": 2,
                "capture_id": "bybit-entry-capture-1",
                "symbol": "BTCUSDT",
                "entry_scenario": {"structure": {"timeframes": ["5m", "15m"]}},
                "v2_decision": {"approved": False, "failed_gate": "NO_TARGET_MEETS_RR"},
            },
        )
        brain_record = SimpleNamespace(
            allowed=False,
            brain_action="HOLD",
            brain_reason="BEAR_NO_TARGET_TIGHT_STOP",
            brain_confidence=96.0,
        )
        lab._persist_candidate_capture(
            capture,
            score={"scalp_score": 72, "swing_score": 48},
            mode="SCALP",
            entry_price=100.0,
            stop_loss=99.0,
            economics={"approved": True, "reward_risk": 1.3},
            decision="REJECTED_BRAIN_AUTHORITY",
            failed_gate="BEAR_NO_TARGET_TIGHT_STOP",
            brain_record=brain_record,
        )

        key = ("ENTRY_V2_CAPTURE_BYBIT_HOSTED_LAB", "bybit-entry-capture-1")
        record = database.rows[key]
        assert record["venue"] == "BYBIT"
        assert record["candidate"]["trade_mode"] == "SCALP"
        assert record["candidate"]["score"] == 72
        assert record["entry_economics"]["approved"] is True
        assert record["brain_authority"]["allowed"] is False
        assert record["brain_authority"]["reason"] == "BEAR_NO_TARGET_TIGHT_STOP"
        assert record["final_decision"] == "REJECTED_BRAIN_AUTHORITY"
        assert record["failed_gate"] == "BEAR_NO_TARGET_TIGHT_STOP"
    finally:
        runner.close()


def test_hosted_candidate_evidence_failure_never_changes_paper_gate_flow():
    database = FakeDatabase()
    runner = _runner(database)
    lab = runner.labs["OKX"]
    try:
        capture = SimpleNamespace(
            capture_id="okx-entry-capture-2",
            symbol="ETHUSDT",
            to_dict=lambda: {
                "capture_id": "okx-entry-capture-2",
                "symbol": "ETHUSDT",
            },
        )

        def broken_append(_record):
            raise OSError("evidence storage unavailable")

        lab.entry_captures.append = broken_append
        # The diagnostic writer is best-effort and cannot raise into the
        # independently controlled Paper entry / Risk / execution path.
        lab._persist_candidate_capture(
            capture,
            score={"swing_score": 83},
            mode="SWING",
            entry_price=2500.0,
            stop_loss=2450.0,
            economics={"approved": True},
            decision="PAPER_POSITION_OPENED",
            position_id="paper-position-okx-1",
        )
    finally:
        runner.close()



def test_closing_hosted_labs_never_stops_main_owned_binance_stream():
    runner = _runner(FakeDatabase())
    binance_stream = runner.labs["BINANCE"].stream
    bybit_stream = runner.labs["BYBIT"].stream
    okx_stream = runner.labs["OKX"].stream

    runner.start()
    runner.close()

    assert binance_stream.started is True
    assert bybit_stream.started is False
    assert okx_stream.started is False
