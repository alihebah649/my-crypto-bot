"""One-process, isolated Paper labs for Binance, Bybit and OKX.

The runner reuses MAIN's Binance public stream and owns one additional Bybit
stream plus OKX's two public sockets. Each venue has its own Paper account,
Trade Manager repository, Brain authority, state snapshot and outcome namespace.
It never shares or mutates MAIN's portfolio, strategy runtime or entry function.
"""
from __future__ import annotations

from copy import deepcopy
import logging
import os
import threading
import time
from typing import Any, Mapping

from core.brain_authority import GuardedBrainAuthority
from core.brain_market_regime import derive_market_breadth
from core.paper_execution_adapter import PaperExecutionAdapter
from core.paper_lab_state import PostgresPaperLabState
from core.paper_outcome_evidence import build_paper_outcome_evidence
from core.paper_risk_overlay import paper_entry_economics
from core.postgres_evidence_store import PostgresEvidenceStore
from dual_mode_strategy import score_symbol
from engine.entry_v2_adapter import EntryV2MarketFacts
from engine.entry_v2_capture import capture_entry_v2
from engine.entry_target_rr import calculate_target_rr
from trade_manager.repository import PositionRepository
from trade_manager.shadow_integration import ShadowTradeManagerRuntime

logger = logging.getLogger("ShadowMain.HostedPaperLabs")

_INTERVALS = ("5m", "15m", "1h", "4h")
_HISTORY_LIMITS = {"5m": 60, "15m": 150, "1h": 60, "4h": 60}
_REQUIRED_HISTORY = {"5m": 20, "15m": 100, "1h": 30, "4h": 30}
_SUPPORTED_VENUES = ("BINANCE", "BYBIT", "OKX")


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _entry_modes(score: Mapping[str, Any]) -> list[str]:
    scalp = str(score.get("scalp_signal") or "").upper() == "BUY"
    swing = str(score.get("swing_signal") or "").upper() == "BUY"
    if not scalp and not swing:
        return []
    if scalp and swing:
        selected = str(score.get("trade_mode") or "").upper()
        if selected not in {"SCALP", "SWING"}:
            selected = (
                "SCALP"
                if float(score.get("scalp_score", 0.0) or 0.0)
                >= float(score.get("swing_score", 0.0) or 0.0)
                else "SWING"
            )
        return [selected]
    return ["SCALP" if scalp else "SWING"]


def _spread_percent(ticker: Mapping[str, Any]) -> float:
    price = float(ticker.get("lastPrice") or 0.0)
    bid = float(ticker.get("bidPrice") or price)
    ask = float(ticker.get("askPrice") or price)
    if price <= 0.0:
        return 0.0
    return max(0.0, (ask - bid) / price * 100.0)


def _entry_v2_shadow(capture: Any) -> dict[str, Any]:
    scenario = capture.entry_scenario
    decision = capture.v2_decision
    structure = scenario.get("structure", {}) if isinstance(scenario, Mapping) else {}
    by_timeframe = structure.get("multi_candle_by_timeframe", {}) if isinstance(structure, Mapping) else {}
    five = by_timeframe.get("5m", {}) if isinstance(by_timeframe, Mapping) else {}
    fifteen = by_timeframe.get("15m", {}) if isinstance(by_timeframe, Mapping) else {}
    failed_gate = str(decision.get("failed_gate") or "").upper()
    risk = scenario.get("risk", {}) if isinstance(scenario, Mapping) else {}
    return {
        "capture_id": capture.capture_id,
        "failed_gate": failed_gate,
        "v2_failed_gate": failed_gate,
        "approved": bool(decision.get("approved")),
        "decision": decision.get("decision"),
        "trade_mode": decision.get("trade_mode"),
        "stop_distance_percent": risk.get("stop_distance_percent"),
        "adaptive_scalp_shadow": dict(capture.adaptive_scalp_shadow or {}),
        "candle_patterns_5m": list(five.get("patterns", []) or []),
        "candle_patterns_15m": list(fifteen.get("patterns", []) or []),
    }


class _VenueLab:
    def __init__(
        self,
        *,
        venue: str,
        stream: Any,
        symbols: list[str],
        database_url: str,
        initial_cash: float,
        fee_rate: float,
        warmup_client: Any = None,
        scan_batch_size: int = 4,
        state_connect_factory: Any = None,
        outcome_connect_factory: Any = None,
    ) -> None:
        self.venue = venue
        self.stream = stream
        self.symbols = tuple(str(s).upper() for s in symbols)
        self.scan_batch_size = max(1, int(scan_batch_size))
        self.scan_cursor = 0
        self.latest_scores: dict[str, dict[str, Any]] = {}
        self.cycles = 0
        self.scored_symbols = 0
        self.entry_candidates = 0
        self.entry_allowed = 0
        self.entry_blocked: dict[str, int] = {}
        self.pause_new_entries = False
        self.last_cycle_at: float | None = None
        self.last_cycle_seconds = 0.0
        self.last_error: str | None = None
        self.persistence_error: str | None = None
        self.warmup_client = warmup_client
        self._warmup_started = False
        self._warmup_thread: threading.Thread | None = None
        self._last_state_save_at = 0.0
        self._reported_closed_ids: set[str] = set()
        self._lock = threading.RLock()

        self.adapter = PaperExecutionAdapter(initial_cash=initial_cash, fee_rate=fee_rate)
        self.repository = PositionRepository()
        self.state = PostgresPaperLabState(
            database_url,
            venue=venue,
            connect_factory=state_connect_factory,
        )
        restored = self.state.load_into(self.adapter, self.repository)
        self.runtime = ShadowTradeManagerRuntime(
            initial_cash=initial_cash,
            fee_rate=fee_rate,
            execution_adapter=self.adapter,
            position_repository=self.repository,
        )
        self.brain = GuardedBrainAuthority()
        # Exit-watchdog regime observations must use this venue's own scored
        # market breadth, never the MAIN Binance or another lab's snapshot.
        self.runtime.exit_watchdog.brain_market_regime_provider = (
            lambda _symbol: derive_market_breadth(self.latest_scores).regime
            if self.latest_scores else "TRANSITION"
        )
        self.outcomes = PostgresEvidenceStore(
            database_url,
            evidence_type=f"PAPER_OUTCOME_{venue}_HOSTED_LAB",
            max_records=10_000,
            connect_factory=outcome_connect_factory,
        )
        previous_outcomes = self.outcomes.read_all()
        if self.outcomes.last_error:
            raise RuntimeError(
                f"{venue} outcome evidence read failed: {self.outcomes.last_error}"
            )
        self._reported_closed_ids = {
            str(row.get("position_id"))
            for row in previous_outcomes
            if row.get("position_id")
        }
        # A new empty state is durably initialized before this lab is exposed.
        if not restored:
            self._save_state(force=True)
        logger.info(
            "[HOSTED-PAPER-LAB] initialized venue=%s restored=%s cash=%.2f positions=%d",
            venue,
            restored,
            self.adapter.balance.cash,
            self.repository.count(),
        )

    def start(self) -> None:
        if self.stream is not None:
            self.stream.start()
        self._start_cold_warmup()

    def _start_cold_warmup(self) -> None:
        if self.warmup_client is None or self._warmup_started:
            return
        self._warmup_started = True
        self._warmup_thread = threading.Thread(
            target=self._seed_history,
            daemon=True,
            name=f"{self.venue.lower()}-paper-lab-warmup",
        )
        self._warmup_thread.start()

    def _seed_history(self) -> None:
        seeded = 0
        failed = 0
        # One bounded cold-start seed per venue. After this, WebSocket updates
        # own the data; the runner never performs periodic REST polling.
        for symbol in self.symbols:
            for interval in _INTERVALS:
                try:
                    rows = self.warmup_client.fetch_klines(
                        symbol, interval, _HISTORY_LIMITS[interval]
                    )
                    count = self.stream.seed_kline_history(symbol, interval, rows or [])
                    if count >= _REQUIRED_HISTORY[interval]:
                        seeded += 1
                    else:
                        failed += 1
                except Exception as exc:
                    failed += 1
                    logger.warning(
                        "[HOSTED-PAPER-LAB-WARMUP] venue=%s symbol=%s interval=%s error=%s",
                        self.venue,
                        symbol,
                        interval,
                        type(exc).__name__,
                    )
                time.sleep(0.15)
        logger.info(
            "[HOSTED-PAPER-LAB-WARMUP] venue=%s seeded_series=%d/%d incomplete=%d",
            self.venue,
            seeded,
            len(self.symbols) * len(_INTERVALS),
            failed,
        )

    def _frames(self, symbol: str) -> dict[str, list[dict[str, Any]]]:
        return {
            interval: self.stream.get_kline_history(
                symbol, interval, _HISTORY_LIMITS[interval]
            )
            for interval in _INTERVALS
        }

    def _ticker_is_fresh(self, ticker: Mapping[str, Any], now: float) -> bool:
        try:
            received = float(ticker.get("received_at") or 0.0)
        except (TypeError, ValueError):
            return False
        return received > 0.0 and max(0.0, now - received) <= 60.0

    def _frames_are_ready(self, frames: Mapping[str, list[dict[str, Any]]], now: float) -> bool:
        for interval, minimum in _REQUIRED_HISTORY.items():
            rows = frames.get(interval) or []
            if len(rows) < minimum:
                return False
            latest = rows[-1]
            try:
                received = float(latest.get("received_at") or 0.0)
            except (TypeError, ValueError):
                return False
            if received <= 0.0 or max(0.0, now - received) > 180.0:
                return False
        return True

    def _record_block(self, reason: str) -> None:
        self.entry_blocked[reason] = int(self.entry_blocked.get(reason, 0)) + 1

    def _try_entry(
        self,
        symbol: str,
        ticker: Mapping[str, Any],
        frames: Mapping[str, list[dict[str, Any]]],
        score: dict[str, Any],
        market_regime: str,
    ) -> None:
        modes = _entry_modes(score)
        if not modes:
            return
        self.entry_candidates += 1
        mode = modes[0]
        price = float(ticker.get("lastPrice") or score.get("price") or 0.0)
        atr = float(score.get("atr") or 0.0)
        if price <= 0.0 or atr <= 0.0:
            self._record_block("INVALID_PRICE_OR_ATR")
            return
        if self.runtime.controller.has_position(symbol):
            self._record_block("EXISTING_VENUE_POSITION")
            return

        stop_loss = price - 2.0 * atr
        if stop_loss <= 0.0 or stop_loss >= price:
            self._record_block("INVALID_STOP")
            return

        btc_rows = self.stream.get_kline_history("BTCUSDT", "1h", 60)
        btc_closed = btc_rows[:-1] if len(btc_rows) > 1 else btc_rows
        if len(btc_closed) >= 3:
            recent_high = max(float(row.get("close") or 0.0) for row in btc_closed[-3:])
            btc_current = float(btc_closed[-1].get("close") or 0.0)
            btc_crashing = bool(
                recent_high > 0.0
                and (btc_current - recent_high) / recent_high <= -0.03
            )
            if btc_crashing:
                self._record_block("BTC_CRASH_GUARD")
                return

        # Risk sizing consumes this venue's own price/ATR snapshot. The
        # runtime is never allowed to size an entry from another exchange.
        self.runtime.update_market(
            symbol,
            price=price,
            bid=float(ticker.get("bidPrice") or price),
            ask=float(ticker.get("askPrice") or price),
            spread_percent=_spread_percent(ticker),
            atr=atr,
            volume_usdt=float(ticker.get("quoteVolume") or 0.0),
            ema100=float(score.get("ema100") or 0.0),
        )

        candidate = dict(score)
        candidate["trade_mode"] = mode
        candidate["signal"] = "BUY"
        candidate["score"] = (
            score.get("scalp_score") if mode == "SCALP" else score.get("swing_score")
        )
        target_rr = calculate_target_rr(
            trade_mode=mode,
            entry_price=price,
            stop_loss=stop_loss,
            candles_by_timeframe=frames,
        )
        stop_distance = (price - stop_loss) / price * 100.0
        spread = _spread_percent(ticker)
        facts = EntryV2MarketFacts(
            legacy_result=candidate,
            candles_5m=frames["5m"],
            candles_15m=frames["15m"],
            candles_1h=frames["1h"],
            candles_4h=frames["4h"],
            stop_distance_percent=stop_distance,
            reward_risk=target_rr.reward_risk,
            spread_percent=spread,
            target_price=target_rr.target_price,
            target_source=target_rr.target_source,
            target_status=target_rr.status,
            btc_guard="PASS",
        )
        capture = capture_entry_v2(symbol, facts)
        v2_shadow = _entry_v2_shadow(capture)
        economics = paper_entry_economics(
            trade_mode=mode,
            entry_price=price,
            stop_loss=stop_loss,
            target_price=target_rr.target_price,
            target_status=target_rr.status,
            reward_risk=target_rr.reward_risk,
            fee_rate=self.adapter.fee_rate,
        )
        if not economics.get("approved", False):
            self._record_block(str(economics.get("reason") or "ENTRY_ECONOMICS_REJECTED"))
            return

        brain_record = self.brain.evaluate_entry(
            symbol,
            candidate,
            trade_mode=mode,
            market_regime=market_regime,
            existing_position=False,
            capture_id=capture.capture_id,
            entry_v2_shadow=v2_shadow,
        )
        if not brain_record.allowed:
            self._record_block(str(brain_record.brain_reason or "BRAIN_REJECTED"))
            return

        position = self.runtime.open_position(
            symbol,
            price,
            stop_loss,
            trade_mode=mode,
            strategy_snapshot=deepcopy(score),
            strategy_snapshot_captured_at=time.time(),
        )
        if position is None:
            trace = self.runtime.last_entry_diagnostics.get(symbol, {}) or {}
            self._record_block(str(trace.get("result") or "TRADE_MANAGER_REJECTED"))
            return

        metadata = {
            "trade_mode": mode,
            "venue_mode": f"{self.venue}_HOSTED_PAPER_LAB",
            "market_data_policy": f"ISOLATED_{self.venue}_WEBSOCKET",
            "market_data_source": self.venue,
            "execution_market_data_source": self.venue,
            "entry_v2_capture_id": capture.capture_id,
            "brain_reason": brain_record.brain_reason,
            "entry_reward_risk": target_rr.reward_risk,
            "entry_target_price": target_rr.target_price,
            "entry_target_status": target_rr.status,
        }
        position.entry_metadata.update(metadata)
        position.metadata.update(metadata)
        position.entry_metadata["brain_authority"] = {
            "allowed": brain_record.allowed,
            "reason": brain_record.brain_reason,
            "confidence": brain_record.brain_confidence,
        }
        self.repository.update(position)
        self.entry_allowed += 1
        self._save_state(force=True)
        logger.info(
            "[HOSTED-PAPER-LAB] OPEN venue=%s symbol=%s mode=%s score=%s price=%.8f stop=%.8f",
            self.venue,
            symbol,
            mode,
            score.get("scalp_score") if mode == "SCALP" else score.get("swing_score"),
            price,
            stop_loss,
        )

    def _update_positions(self, now: float) -> None:
        # Positions are marked only with this venue's own ticker. No Binance
        # price is ever passed into a Bybit/OKX Trade Manager runtime.
        for position in list(self.repository.get_open_positions()):
            ticker = self.stream.get_latest_ticker(position.symbol)
            if not isinstance(ticker, Mapping) or not self._ticker_is_fresh(ticker, now):
                continue
            price = float(ticker.get("lastPrice") or 0.0)
            if price <= 0.0:
                continue
            score = self.latest_scores.get(position.symbol, {})
            self.runtime.update_market(
                position.symbol,
                price=price,
                bid=float(ticker.get("bidPrice") or price),
                ask=float(ticker.get("askPrice") or price),
                spread_percent=_spread_percent(ticker),
                atr=float(score.get("atr") or 0.0),
                volume_usdt=float(ticker.get("quoteVolume") or 0.0),
                ema100=float(score.get("ema100") or 0.0),
            )
        # Run the normal Part-8 exit watchdog against only this venue's
        # repository and market context (the provider was rebound at init).
        if self.repository.get_open_positions():
            self.runtime.run_exit_watchdog()

    def _persist_new_outcomes(self) -> None:
        for position in self.repository.get_closed_positions():
            position_id = str(position.position_id)
            if position_id in self._reported_closed_ids:
                continue
            evidence = build_paper_outcome_evidence(position)
            evidence["venue"] = self.venue
            evidence["venue_mode"] = f"{self.venue}_HOSTED_PAPER_LAB"
            evidence["market_data_policy"] = f"ISOLATED_{self.venue}_WEBSOCKET"
            if self.outcomes.append(evidence):
                self._reported_closed_ids.add(position_id)
            elif self.outcomes.last_error:
                logger.error(
                    "[HOSTED-PAPER-LAB] outcome persistence failed venue=%s position=%s error=%s",
                    self.venue,
                    position_id,
                    self.outcomes.last_error,
                )
            else:
                # A prior append may have committed before a connection reset.
                self._reported_closed_ids.add(position_id)

    def _save_state(self, *, force: bool = False) -> None:
        now = time.time()
        if not force and now - self._last_state_save_at < 60.0:
            return
        try:
            self.state.save(self.adapter, self.repository)
            self._last_state_save_at = now
            self.persistence_error = None
        except Exception as exc:
            self.persistence_error = f"{type(exc).__name__}: {exc}"
            logger.error(
                "[HOSTED-PAPER-LAB] state persistence blocked venue=%s error=%s",
                self.venue,
                self.persistence_error,
            )

    def process_cycle(self, now: float | None = None) -> None:
        started = time.monotonic()
        current = time.time() if now is None else float(now)
        with self._lock:
            self.cycles += 1
            self.last_cycle_at = current
            stream_state = self.stream.snapshot(now=current) if self.stream else {}
            if not stream_state.get("connected", False):
                self.last_error = str(stream_state.get("last_error") or "WEBSOCKET_NOT_CONNECTED")
            else:
                self.last_error = None

            # Refresh all already-open positions every cycle; only a small
            # rotating slice of the universe is rescored for new entries.
            self._update_positions(current)
            start = self.scan_cursor
            batch = [
                self.symbols[(start + offset) % len(self.symbols)]
                for offset in range(min(self.scan_batch_size, len(self.symbols)))
            ]
            self.scan_cursor = (start + len(batch)) % max(1, len(self.symbols))
            for symbol in batch:
                ticker = self.stream.get_latest_ticker(symbol) if self.stream else None
                if not isinstance(ticker, Mapping) or not self._ticker_is_fresh(ticker, current):
                    self._record_block("STALE_OR_MISSING_TICKER")
                    continue
                frames = self._frames(symbol)
                if not self._frames_are_ready(frames, current):
                    self._record_block("VENUE_CANDLE_HISTORY_NOT_READY")
                    continue
                score = score_symbol(
                    symbol,
                    ticker,
                    frames["15m"],
                    frames["5m"],
                    frames["1h"],
                    frames["4h"],
                )
                score["market_data_source"] = self.venue
                score["market_data_transport"] = "WEBSOCKET"
                self.latest_scores[symbol] = score
                self.scored_symbols += 1

            if batch and self.latest_scores:
                breadth_ready = len(self.latest_scores) >= len(self.symbols)
                regime = derive_market_breadth(self.latest_scores).regime if breadth_ready else "TRANSITION"
                for symbol in batch:
                    score = self.latest_scores.get(symbol)
                    if not isinstance(score, dict):
                        continue
                    ticker = self.stream.get_latest_ticker(symbol) if self.stream else None
                    if not isinstance(ticker, Mapping):
                        continue
                    if _entry_modes(score):
                        if not breadth_ready:
                            self._record_block("VENUE_MARKET_BREADTH_WARMING")
                            continue
                        if self.persistence_error:
                            self._record_block("PAPER_LAB_STATE_NOT_DURABLE")
                            continue
                        if self.pause_new_entries:
                            self._record_block("HOSTED_LAB_RESOURCE_GUARD")
                            continue
                        if not self._ticker_is_fresh(ticker, current):
                            self._record_block("STALE_OR_MISSING_TICKER")
                            continue
                        if not self._frames_are_ready(self._frames(symbol), current):
                            self._record_block("VENUE_CANDLE_HISTORY_NOT_READY")
                            continue
                        self._try_entry(
                            symbol,
                            ticker,
                            self._frames(symbol),
                            score,
                            regime,
                        )

            self._persist_new_outcomes()
            self._save_state()
            self.last_cycle_seconds = round(time.monotonic() - started, 4)

    def snapshot(self) -> dict[str, Any]:
        stream = self.stream.snapshot() if self.stream else {"available": False}
        return {
            "venue": self.venue,
            "enabled": True,
            "stream": stream,
            "cycles": self.cycles,
            "scored_symbols_total": self.scored_symbols,
            "entry_candidates": self.entry_candidates,
            "entry_allowed": self.entry_allowed,
            "new_entries_paused": self.pause_new_entries,
            "entry_blocked": dict(self.entry_blocked),
            "open_positions": len(self.repository.get_open_positions()),
            "closed_positions": len(self.repository.get_closed_positions()),
            "paper_cash": round(float(self.adapter.balance.cash), 4),
            "last_cycle_seconds": self.last_cycle_seconds,
            "last_error": self.last_error,
            "persistence_error": self.persistence_error,
        }

    def close(self) -> None:
        if self.stream is not None:
            self.stream.stop()
        self.state.close()
        self.outcomes.close()


class HostedPaperLabRunner:
    """Optional Paper-only venue lab runner hosted by the MAIN Render process."""

    def __init__(
        self,
        *,
        symbols: list[str],
        binance_stream: Any,
        bybit_stream: Any,
        okx_stream: Any,
        database_url: str,
        bybit_client: Any = None,
        okx_client: Any = None,
        initial_cash: float = 1000.0,
        fee_rate: float = 0.001,
        scan_batch_size: int = 4,
    ) -> None:
        if not database_url:
            raise ValueError("PAPER_EVIDENCE_DATABASE_URL is required for hosted Paper labs")
        if binance_stream is None or bybit_stream is None or okx_stream is None:
            raise ValueError("all three venue WebSocket streams are required")
        self.enabled = True
        self.start_error: str | None = None
        self._lock = threading.RLock()
        self._last_cycle_seconds = 0.0
        self._cycles = 0
        self._max_memory_mb = 0.0
        self._last_warning = None
        self.labs: dict[str, _VenueLab] = {}
        try:
            self.labs["BINANCE"] = _VenueLab(
                venue="BINANCE",
                stream=binance_stream,
                symbols=symbols,
                database_url=database_url,
                initial_cash=initial_cash,
                fee_rate=fee_rate,
                scan_batch_size=scan_batch_size,
            )
            self.labs["BYBIT"] = _VenueLab(
                venue="BYBIT",
                stream=bybit_stream,
                symbols=symbols,
                database_url=database_url,
                initial_cash=initial_cash,
                fee_rate=fee_rate,
                warmup_client=bybit_client,
                scan_batch_size=scan_batch_size,
            )
            self.labs["OKX"] = _VenueLab(
                venue="OKX",
                stream=okx_stream,
                symbols=symbols,
                database_url=database_url,
                initial_cash=initial_cash,
                fee_rate=fee_rate,
                warmup_client=okx_client,
                scan_batch_size=scan_batch_size,
            )
        except Exception as exc:
            for lab in self.labs.values():
                try:
                    lab.close()
                except Exception:
                    pass
            self.labs.clear()
            self.enabled = False
            self.start_error = f"{type(exc).__name__}: {exc}"
            logger.error("[HOSTED-PAPER-LABS] disabled during restore: %s", self.start_error)

    def start(self) -> None:
        if not self.enabled:
            return
        for venue in _SUPPORTED_VENUES:
            self.labs[venue].start()
        logger.warning(
            "[HOSTED-PAPER-LABS] started in MAIN process venues=BINANCE,BYBIT,OKX "
            "mode=PAPER_ONLY batch_per_venue=%d",
            next(iter(self.labs.values())).scan_batch_size,
        )

    def process_cycle(self) -> None:
        if not self.enabled:
            return
        started = time.monotonic()
        with self._lock:
            # Binance reuses MAIN's existing relay stream. The remaining two
            # feeds are venue-isolated public WebSockets hosted in this process.
            for venue in _SUPPORTED_VENUES:
                lab = self.labs[venue]
                try:
                    lab.process_cycle()
                except Exception as exc:
                    lab.last_error = f"{type(exc).__name__}: {exc}"
                    logger.exception("[HOSTED-PAPER-LAB] cycle failed venue=%s", venue)
            self._cycles += 1
            self._last_cycle_seconds = round(time.monotonic() - started, 4)
            self._max_memory_mb = max(self._max_memory_mb, self._memory_mb())
            # The memory circuit stops new lab entries, but keeps WebSockets
            # alive so existing Paper positions can still be managed safely.
            if self._max_memory_mb >= 400.0 and self._last_warning is None:
                self._last_warning = "MEMORY_GUARD_NEW_ENTRIES_PAUSED"
                logger.error(
                    "[HOSTED-PAPER-LABS] resource guard activated rss_mb=%.1f; "
                    "new lab entries paused, existing positions remain managed",
                    self._max_memory_mb,
                )
            if self._last_memory_guard():
                for lab in self.labs.values():
                    lab.pause_new_entries = True

    def _last_memory_guard(self) -> bool:
        return self._max_memory_mb >= 400.0

    @staticmethod
    def _memory_mb() -> float:
        try:
            import resource
            value = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
            # Linux reports KB; macOS reports bytes.
            return value / 1024.0 if value > 10_000 else value / (1024.0 * 1024.0)
        except Exception:
            return 0.0

    def snapshot(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "start_error": self.start_error,
            "cycles": self._cycles,
            "last_cycle_seconds": self._last_cycle_seconds,
            "process_max_rss_mb": self._max_memory_mb,
            "memory_guard": self._last_memory_guard(),
            "venues": {
                venue: lab.snapshot()
                for venue, lab in self.labs.items()
            },
        }

    def close(self) -> None:
        for lab in self.labs.values():
            lab.close()


def create_hosted_paper_lab_runner(**kwargs) -> HostedPaperLabRunner | None:
    """Construct only when explicitly enabled; the default MAIN path is unchanged."""
    if not _bool_env("PAPER_HOSTED_VENUE_LABS", False):
        return None
    try:
        return HostedPaperLabRunner(**kwargs)
    except Exception as exc:
        logger.exception("[HOSTED-PAPER-LABS] initialization failed")
        # A lab integration failure must never prevent the MAIN Paper bot boot.
        return None


__all__ = ["HostedPaperLabRunner", "create_hosted_paper_lab_runner"]
