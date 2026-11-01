from __future__ import annotations

import json
import threading
import time
from types import SimpleNamespace

import pytest

from core.hosted_paper_labs import HostedPaperLabRunner
from trade_manager.models import Position, PositionSide, PositionStatus
from trade_manager.risk_manager import PositionExitDecision, PositionExitReason


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


class FakeWarmupClient:
    def __init__(self, supported_symbols, missing_series=None):
        self.supported_symbols = set(supported_symbols)
        self.missing_series = set(missing_series or ())
        self.fetch_tickers_calls = 0
        self.fetch_kline_calls = []

    def fetch_tickers(self, symbols):
        self.fetch_tickers_calls += 1
        return {
            symbol: {"symbol": symbol, "lastPrice": 100.0}
            for symbol in symbols
            if symbol in self.supported_symbols
        }

    def fetch_klines(self, symbol, interval, limit):
        self.fetch_kline_calls.append((symbol, interval, limit))
        if (symbol, interval) in self.missing_series:
            return []
        now = int(time.time() * 1000)
        interval_ms = {"5m": 300000, "15m": 900000, "1h": 3600000, "4h": 14400000}[interval]
        return [
            {
                "open_time": now - (limit - index) * interval_ms,
                "close_time": now - (limit - index) * interval_ms + interval_ms - 1,
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.0,
                "volume": 1000.0,
            }
            for index in range(limit)
        ]


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


def test_monitor_only_can_run_one_venue_without_postgres_or_extra_streams():
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT"]
    binance_stream = FakeStream("BINANCE", symbols)
    binance_stream.start()
    bybit_stream = FakeStream("BYBIT", symbols)

    runner = HostedPaperLabRunner(
        symbols=symbols,
        binance_stream=binance_stream,
        bybit_stream=bybit_stream,
        okx_stream=None,
        database_url=None,
        enabled_venues=("BYBIT",),
        monitor_only=True,
        scan_batch_size=2,
    )
    try:
        assert runner.enabled is True
        assert runner.enabled_venues == ("BYBIT",)
        assert set(runner.labs) == {"BYBIT"}
        lab = runner.labs["BYBIT"]
        assert lab.monitor_only is True
        assert lab.state is None
        assert lab.outcomes.max_records == 10_000
        assert lab.entry_captures.max_records == 2_000

        runner.start()
        runner.process_cycle()

        assert bybit_stream.started is True
        assert binance_stream.started is True
        assert runner.snapshot()["mode"] == "MONITOR_ONLY"
        assert runner.snapshot()["enabled_venues"] == ["BYBIT"]
        assert lab.cycles == 1
    finally:
        runner.close()


def test_monitor_only_memory_guard_stops_hosted_feed_but_never_main_binance():
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT"]
    binance_stream = FakeStream("BINANCE", symbols)
    binance_stream.start()
    bybit_stream = FakeStream("BYBIT", symbols)
    runner = HostedPaperLabRunner(
        symbols=symbols,
        binance_stream=binance_stream,
        bybit_stream=bybit_stream,
        database_url=None,
        enabled_venues=("BYBIT",),
        monitor_only=True,
        scan_batch_size=2,
    )
    try:
        runner.start()
        runner._max_memory_mb = 405.0
        runner.process_cycle()

        assert runner.snapshot()["memory_guard"] is True
        assert runner.snapshot()["monitor_streams_stopped_by_guard"] is True
        assert bybit_stream.started is False
        assert binance_stream.started is True
        assert runner.labs["BYBIT"].pause_new_entries is True
    finally:
        runner.close()


def test_monitor_only_scores_candidates_without_opening_positions_or_writing_evidence(monkeypatch):
    import core.hosted_paper_labs as hosted_module

    symbols = ["BTCUSDT"]
    binance_stream = FakeStream("BINANCE", symbols)
    binance_stream.start()
    bybit_stream = FakeStream("BYBIT", symbols)
    runner = HostedPaperLabRunner(
        symbols=symbols,
        binance_stream=binance_stream,
        bybit_stream=bybit_stream,
        database_url=None,
        enabled_venues=("BYBIT",),
        monitor_only=True,
        scan_batch_size=1,
    )
    lab = runner.labs["BYBIT"]
    try:
        lab.symbols = ("BTCUSDT",)
        lab.universe_ready = True
        frames = {"5m": [{}], "15m": [{}], "1h": [{}], "4h": [{}]}
        monkeypatch.setattr(lab, "_frames", lambda _symbol: frames)
        monkeypatch.setattr(lab, "_frames_are_ready", lambda _frames, _now: True)
        monkeypatch.setattr(
            hosted_module,
            "score_symbol",
            lambda *_args: {
                "trade_mode": "SWING",
                "signal": "BUY",
                "score": 91,
                "swing_score": 91,
                "swing_signal": "BUY",
                "scalp_score": 20,
                "scalp_signal": "HOLD",
            },
        )

        def forbidden_entry(*_args, **_kwargs):
            pytest.fail("monitor-only must never invoke the Paper entry path")

        monkeypatch.setattr(lab, "_try_entry", forbidden_entry)
        cash_before = lab.adapter.balance.cash
        lab.process_cycle()

        assert lab.scored_symbols == 1
        assert lab.monitor_candidates == 1
        assert lab.entry_blocked["MONITOR_ONLY_ENTRIES_DISABLED"] == 1
        assert lab.repository.get_all() == []
        assert lab.adapter.balance.cash == pytest.approx(cash_before)
        assert lab.state is None
        assert lab.persistence_error is None
        assert lab.outcome_persistence_error is None
    finally:
        runner.close()


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



def test_startup_memory_abort_cancels_background_cold_warmup(monkeypatch):
    database = FakeDatabase()
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT"]
    binance_stream = FakeStream("BINANCE", symbols)
    binance_stream.start()
    bybit_stream = FakeStream("BYBIT", symbols)
    okx_stream = FakeStream("OKX", symbols)
    seed_calls = []
    bybit_stream.seed_kline_history = (
        lambda symbol, interval, rows: seed_calls.append((symbol, interval)) or len(list(rows))
    )

    class SlowWarmupClient(FakeWarmupClient):
        def __init__(self, supported_symbols):
            super().__init__(supported_symbols)
            self.first_candle_fetch_started = threading.Event()

        def fetch_klines(self, symbol, interval, limit):
            self.first_candle_fetch_started.set()
            time.sleep(0.1)
            return super().fetch_klines(symbol, interval, limit)

    warmup_client = SlowWarmupClient(symbols)
    memory_samples = 0

    def memory_mb():
        nonlocal memory_samples
        memory_samples += 1
        # Three constructor samples and the Binance-start sample stay below
        # the guard. The Bybit-start sample trips it after its warmup thread
        # has entered an in-flight REST request.
        if memory_samples == 5:
            assert warmup_client.first_candle_fetch_started.wait(timeout=1.0)
            return 405.0
        return 300.0

    monkeypatch.setattr(
        HostedPaperLabRunner,
        "_memory_mb",
        staticmethod(memory_mb),
    )
    runner = HostedPaperLabRunner(
        symbols=symbols,
        binance_stream=binance_stream,
        bybit_stream=bybit_stream,
        okx_stream=okx_stream,
        database_url="postgres://test",
        bybit_client=warmup_client,
        okx_client=FakeWarmupClient(symbols),
        initial_cash=1000.0,
        fee_rate=0.001,
        scan_batch_size=2,
        connect_factory=lambda _url: FakeConnection(database),
    )

    with pytest.raises(RuntimeError, match="startup memory guard"):
        runner.start()

    warmup_thread = runner.labs["BYBIT"]._warmup_thread
    assert warmup_thread is not None
    assert runner.started_venues == ["BINANCE", "BYBIT"]
    # Paper mode may have restored open positions, so keep its own feed alive
    # for exit management while cancelling the incomplete cold-start REST work.
    assert bybit_stream.started is True
    assert okx_stream.started is False
    assert runner.snapshot()["monitor_streams_stopped_by_guard"] is False
    runner.close()

    assert not warmup_thread.is_alive()
    assert runner.labs["BYBIT"].snapshot()["warmup_cancelled"] is True
    assert seed_calls == []
    assert bybit_stream.started is False
    assert okx_stream.started is False


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



def test_hosted_lab_compacts_old_synchronous_paper_order_responses():
    runner = _runner(FakeDatabase())
    lab = runner.labs["BINANCE"]
    try:
        lab.adapter.orders = {
            f"PAPER-{index}": {"order": index}
            for index in range(2005)
        }
        removed = lab._compact_order_history(keep=1000)

        assert removed == 1005
        assert len(lab.adapter.orders) == 1000
        assert next(iter(lab.adapter.orders)) == "PAPER-1005"
        assert list(lab.adapter.orders)[-1] == "PAPER-2004"
    finally:
        runner.close()



def test_hosted_lab_preflight_limits_scoring_to_supported_spot_symbols():
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT"]
    database = FakeDatabase()
    client = FakeWarmupClient({"BTCUSDT", "ETHUSDT", "LINKUSDT"})
    runner = HostedPaperLabRunner(
        symbols=symbols,
        binance_stream=FakeStream("BINANCE", symbols),
        bybit_stream=FakeStream("BYBIT", symbols),
        okx_stream=FakeStream("OKX", symbols),
        database_url="postgres://test",
        bybit_client=client,
        okx_client=FakeWarmupClient(set(symbols)),
        initial_cash=1000.0,
        fee_rate=0.001,
        scan_batch_size=2,
        connect_factory=lambda _url: FakeConnection(database),
    )
    try:
        bybit = runner.labs["BYBIT"]
        bybit._seed_history()
        assert client.fetch_tickers_calls == 1
        assert bybit.universe_ready is True
        assert bybit.symbols == ("BTCUSDT", "ETHUSDT", "LINKUSDT")
        assert bybit.unsupported_symbols == ("SOLUSDT",)
        assert len(client.fetch_kline_calls) == 3 * 4
        assert bybit.snapshot()["supported_symbol_count"] == 3
        assert bybit.snapshot()["unsupported_symbols"] == ["SOLUSDT"]
    finally:
        runner.close()


def test_hosted_lab_preflight_requires_btc_spot_market():
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    database = FakeDatabase()
    client = FakeWarmupClient({"ETHUSDT", "SOLUSDT"})
    runner = HostedPaperLabRunner(
        symbols=symbols,
        binance_stream=FakeStream("BINANCE", symbols),
        bybit_stream=FakeStream("BYBIT", symbols),
        okx_stream=FakeStream("OKX", symbols),
        database_url="postgres://test",
        bybit_client=client,
        okx_client=FakeWarmupClient(set(symbols)),
        connect_factory=lambda _url: FakeConnection(database),
    )
    try:
        bybit = runner.labs["BYBIT"]
        bybit._seed_history()
        assert bybit.universe_ready is False
        assert bybit.warmup_error == "BTCUSDT_OR_SPOT_UNIVERSE_UNAVAILABLE"
        assert bybit.snapshot()["warmup_expected_series"] == 2 * 4
        bybit.process_cycle()
        assert bybit.entry_blocked["VENUE_SPOT_UNIVERSE_NOT_READY"] == 1
    finally:
        runner.close()


def test_failed_paper_state_commit_rolls_back_entry_and_pauses_retry(monkeypatch):
    runner = _runner(FakeDatabase())
    lab = runner.labs["BYBIT"]
    try:
        lab.runtime.update_market(
            "BTCUSDT", price=100.0, bid=99.99, ask=100.01,
            spread_percent=0.02, atr=1.0,
            volume_usdt=1_000_000.0, ema100=90.0,
        )
        account = lab.adapter.export_snapshot()
        positions = lab.repository.export_snapshot()
        orders = dict(lab.adapter.orders)
        opened = lab.runtime.open_position(
            "BTCUSDT", 100.0, 95.0, trade_mode="SCALP"
        )
        assert opened is not None

        def fail_save(_adapter, _repository):
            raise OSError("test state persistence failure")

        monkeypatch.setattr(lab.state, "save", fail_save)
        assert lab._rollback_unpersisted_entry(account, positions, orders) is False
        assert lab.adapter.balance.cash == pytest.approx(account["cash"])
        assert lab.adapter.balance.assets == account["assets"]
        assert lab.repository.get_open_positions() == []
        assert lab.adapter.orders == orders
        assert lab.persistence_error is not None
    finally:
        runner.close()



def test_hosted_lab_excludes_one_symbol_with_incomplete_cold_history_without_freezing_venue():
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT"]
    database = FakeDatabase()
    client = FakeWarmupClient(
        set(symbols),
        missing_series={("SOLUSDT", "15m")},
    )
    runner = HostedPaperLabRunner(
        symbols=symbols,
        binance_stream=FakeStream("BINANCE", symbols),
        bybit_stream=FakeStream("BYBIT", symbols),
        okx_stream=FakeStream("OKX", symbols),
        database_url="postgres://test",
        bybit_client=client,
        okx_client=FakeWarmupClient(set(symbols)),
        initial_cash=1000.0,
        fee_rate=0.001,
        scan_batch_size=2,
        connect_factory=lambda _url: FakeConnection(database),
    )
    try:
        bybit = runner.labs["BYBIT"]
        bybit._seed_history()
        assert bybit.universe_ready is True
        assert bybit.symbols == ("BTCUSDT", "ETHUSDT", "LINKUSDT")
        assert bybit.warmup_incomplete_symbols == ("SOLUSDT",)
        assert bybit.snapshot()["scoring_symbol_count"] == 3
    finally:
        runner.close()



def test_hosted_lab_outcome_write_failure_is_visible_and_blocks_future_entries(monkeypatch):
    import core.hosted_paper_labs as hosted_module

    runner = _runner(FakeDatabase())
    lab = runner.labs["OKX"]
    try:
        lab.repository.get_closed_positions = lambda: [
            SimpleNamespace(position_id="okx-closed-pending-outcome")
        ]
        monkeypatch.setattr(
            hosted_module,
            "build_paper_outcome_evidence",
            lambda position: {"position_id": position.position_id},
        )

        def fail_append(_record):
            lab.outcomes.last_error = "database write unavailable"
            return False

        lab.outcomes.append = fail_append
        lab._persist_new_outcomes()

        assert lab.outcome_persistence_error == "database write unavailable"
        assert lab.snapshot()["outcome_persistence_error"] == "database write unavailable"
        assert "okx-closed-pending-outcome" not in lab._reported_closed_ids
    finally:
        runner.close()


def test_hosted_lab_entry_capture_retention_is_bounded_per_venue():
    runner = _runner(FakeDatabase())
    try:
        assert all(
            lab.entry_captures.max_records == 2_000
            for lab in runner.labs.values()
        )
    finally:
        runner.close()



def test_hosted_scalp_freshness_guard_matches_main_five_minute_audit():
    from core.entry_freshness_audit import (
        audit_5m_entry_freshness,
        entry_execution_freshness_allowed,
    )

    now = 2_000_000.0
    stale_decision = {
        "open_time": int((now - 700.0) * 1000),
        "close_time": int((now - 400.0) * 1000),
    }
    current_open = {
        "open_time": int((now - 100.0) * 1000),
        "close_time": int((now + 200.0) * 1000),
    }
    audit = audit_5m_entry_freshness(
        candles_5m=[stale_decision, current_open],
        captured_at=now,
    )

    assert audit["state"] == "STALE"
    assert audit["decision_candle_age_seconds"] == pytest.approx(400.0, abs=0.002)
    assert entry_execution_freshness_allowed(audit, "SCALP") is False
    assert entry_execution_freshness_allowed(audit, "SWING") is True


def test_hosted_swing_candidate_obeys_symbol_loss_cooldown():
    runner = _runner(FakeDatabase())
    lab = runner.labs["BYBIT"]
    try:
        losing = Position(
            position_id="bybit-recent-loss",
            symbol="ETHUSDT",
            side=PositionSide.LONG,
            status=PositionStatus.CLOSED,
            quantity=0.1,
            entry_price=100.0,
            current_price=99.0,
            stop_loss=95.0,
            take_profit=110.0,
            opened_at=time.time() - 3600.0,
            closed_at=time.time() - 60.0,
            realized_pnl=-1.0,
            entry_metadata={"trade_mode": "SWING"},
            metadata={"trade_mode": "SWING"},
        )
        lab.repository.add(losing)

        candidate = {
            "trade_mode": "SWING",
            "signal": "BUY",
            "score": 90,
            "swing_score": 90,
            "swing_signal": "BUY",
            "scalp_score": 20,
            "scalp_signal": "HOLD",
            "atr": 1.0,
            "ema100": 90.0,
        }
        ticker = {
            "lastPrice": 100.0,
            "bidPrice": 99.99,
            "askPrice": 100.01,
            "quoteVolume": 1_000_000.0,
            "received_at": time.time(),
        }
        frames = {"5m": [], "15m": [], "1h": [], "4h": []}

        lab._try_entry("ETHUSDT", ticker, frames, candidate, "BULLISH")

        assert lab.entry_blocked["LOSS_COOLDOWN"] == 1
        eth_positions = lab.repository.get_by_symbol("ETHUSDT")
        assert [position.position_id for position in eth_positions] == [
            "bybit-recent-loss"
        ]
        assert all(position.status is PositionStatus.CLOSED for position in eth_positions)
    finally:
        runner.close()


def test_hosted_swing_keeps_main_strong_btc_crash_exception():
    from core.paper_risk_overlay import strong_bullish_btc_exception

    score = {
        "trade_mode": "SWING",
        "signal": "BUY",
        "score": 92,
        "swing_score": 92,
        "swing_signal": "BUY",
        "swing_reasons": ["EMA100_TREND"],
        "pattern_confirmed": True,
        "mtf_aligned_bullish": True,
    }
    assert strong_bullish_btc_exception(score) is True


def test_hosted_profit_protection_closes_position_before_exit_watchdog():
    runner = _runner(FakeDatabase())
    lab = runner.labs["OKX"]
    try:
        lab.runtime.update_market(
            "BTCUSDT",
            price=100.0,
            bid=99.99,
            ask=100.01,
            spread_percent=0.02,
            atr=1.0,
            volume_usdt=1_000_000.0,
            ema100=95.0,
        )
        position = lab.runtime.open_position(
            "BTCUSDT", 100.0, 95.0, trade_mode="SCALP"
        )
        assert position is not None
        position.highest_price = 110.0
        position.max_profit_percent = 10.0
        lab.repository.update(position)
        lab.stream.prices["BTCUSDT"] = 108.0

        lab._update_positions(time.time())

        closed = lab.repository.get(position.position_id)
        assert closed.status.name == "CLOSED"
        assert closed.exit_metadata["paper_profit_protection"] is True
        assert closed.exit_metadata["paper_profit_protection_detail"]["triggered"] is True
    finally:
        runner.close()



def test_hosted_lab_allows_opposite_lane_but_blocks_same_lane_position():
    runner = _runner(FakeDatabase())
    lab = runner.labs["BYBIT"]
    try:
        swing = Position(
            position_id="bybit-swing-position",
            symbol="ETHUSDT",
            side=PositionSide.LONG,
            status=PositionStatus.OPEN,
            quantity=0.1,
            entry_price=100.0,
            current_price=100.0,
            stop_loss=95.0,
            take_profit=110.0,
            entry_metadata={"trade_mode": "SWING"},
            metadata={"trade_mode": "SWING"},
        )
        lab.repository.add(swing)

        assert lab._active_trade_modes("ETHUSDT") == {"SWING"}
        assert lab._has_active_lane_position("ETHUSDT", "SWING") is True
        assert lab._has_active_lane_position("ETHUSDT", "SCALP") is False

        scalp = Position(
            position_id="bybit-scalp-position",
            symbol="ETHUSDT",
            side=PositionSide.LONG,
            status=PositionStatus.OPEN,
            quantity=0.1,
            entry_price=100.0,
            current_price=100.0,
            stop_loss=98.0,
            take_profit=104.0,
            entry_metadata={"trade_mode": "SCALP"},
            metadata={"trade_mode": "SCALP"},
        )
        lab.repository.add(scalp)

        assert lab._active_trade_modes("ETHUSDT") == {"SWING", "SCALP"}
        assert lab._has_active_lane_position("ETHUSDT", "SWING") is True
        assert lab._has_active_lane_position("ETHUSDT", "SCALP") is True
    finally:
        runner.close()


def test_hosted_lab_stop_fill_wrapper_records_stop_price_and_observed_price():
    runner = _runner(FakeDatabase())
    lab = runner.labs["OKX"]
    try:
        position = Position(
            position_id="okx-stop-fill-position",
            symbol="BTCUSDT",
            side=PositionSide.LONG,
            status=PositionStatus.OPEN,
            quantity=0.1,
            entry_price=100.0,
            current_price=94.0,
            stop_loss=95.0,
            take_profit=110.0,
            entry_metadata={"trade_mode": "SCALP"},
            metadata={"trade_mode": "SCALP"},
        )
        lab.repository.add(position)

        def fake_execute(position_id, decision):
            closed = lab.repository.get(position_id)
            closed.status = PositionStatus.CLOSED
            closed.closed_at = time.time()
            closed.exit_metadata["reason"] = decision.reason.name
            lab.repository.update(closed)
            return closed

        decision = PositionExitDecision(
            True,
            PositionExitReason.STOP_LOSS,
            94.0,
            "test stop",
        )
        result = lab._execute_decision_with_stop_fill(
            fake_execute,
            position.position_id,
            decision,
        )

        assert result.status is PositionStatus.CLOSED
        assert result.exit_metadata["paper_stop_fill"] is True
        assert result.exit_metadata["paper_stop_price"] == pytest.approx(95.0)
        assert result.exit_metadata["paper_observed_price_at_trigger"] == pytest.approx(94.0)
        assert result.exit_metadata["paper_stop_reason"] == "STOP_LOSS"
    finally:
        runner.close()



def test_hosted_lab_part6_sees_main_lane_caps_per_independent_account():
    runner = _runner(FakeDatabase())
    lab = runner.labs["BYBIT"]
    try:
        for index in range(15):
            lab.repository.add(Position(
                position_id=f"bybit-scalp-{index}",
                symbol=f"SCALP{index}USDT",
                side=PositionSide.LONG,
                status=PositionStatus.OPEN,
                quantity=0.1,
                entry_price=100.0,
                current_price=100.0,
                stop_loss=98.0,
                take_profit=104.0,
                entry_metadata={"trade_mode": "SCALP"},
                metadata={"trade_mode": "SCALP"},
            ))
        for index in range(10):
            lab.repository.add(Position(
                position_id=f"bybit-swing-{index}",
                symbol=f"SWING{index}USDT",
                side=PositionSide.LONG,
                status=PositionStatus.OPEN,
                quantity=0.1,
                entry_price=100.0,
                current_price=100.0,
                stop_loss=95.0,
                take_profit=110.0,
                entry_metadata={"trade_mode": "SWING"},
                metadata={"trade_mode": "SWING"},
            ))

        account = lab.runtime.portfolio_provider.snapshot()
        assert account.open_positions == 25
        assert account.scalp_open_positions == 15
        assert account.swing_open_positions == 10
        assert lab.runtime.risk_config.exposure.max_scalp_positions == 15
        assert lab.runtime.risk_config.exposure.max_swing_positions == 10
        assert lab.runtime.risk_config.exposure.max_open_positions == 25
        health = lab.snapshot()
        assert health["open_positions"] == 25
        assert health["open_scalp_positions"] == 15
        assert health["open_swing_positions"] == 10
        assert health["risk_limits"] == {
            "max_open_positions": 25,
            "max_scalp_positions": 15,
            "max_swing_positions": 10,
        }

        lab.runtime.update_market(
            "OVER_CAP_SCALP",
            price=100.0,
            bid=99.99,
            ask=100.01,
            spread_percent=0.02,
            atr=1.0,
            volume_usdt=1_000_000.0,
            ema100=95.0,
        )
        scalp_result = lab.runtime.open_position(
            "OVER_CAP_SCALP", 100.0, 98.0, trade_mode="SCALP"
        )
        assert scalp_result is None
        assert "MAX_OPEN_SCALP_POSITIONS" in str(
            lab.runtime.last_entry_diagnostics["OVER_CAP_SCALP"]["risk_reason"]
        )

        lab.runtime.update_market(
            "OVER_CAP_SWING",
            price=100.0,
            bid=99.99,
            ask=100.01,
            spread_percent=0.02,
            atr=1.0,
            volume_usdt=1_000_000.0,
            ema100=95.0,
        )
        swing_result = lab.runtime.open_position(
            "OVER_CAP_SWING", 100.0, 95.0, trade_mode="SWING"
        )
        assert swing_result is None
        assert "MAX_OPEN_SWING_POSITIONS" in str(
            lab.runtime.last_entry_diagnostics["OVER_CAP_SWING"]["risk_reason"]
        )
    finally:
        runner.close()
