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


def _lane_context_missing(score: Mapping[str, Any], mode: str) -> list[str]:
    """Fail closed when the selected strategy lane has incomplete source context."""
    lane = str(mode or "").upper()
    source_mode = str(score.get("trade_mode") or "").upper()
    missing: list[str] = []
    if lane == "SCALP":
        lane_score = score.get("scalp_score")
        if lane_score is None and not (
            source_mode == "SCALP" and score.get("score") is not None
        ):
            missing.append("scalp_score")
        if not (
            "scalp_confirmed_reversal" in score
            or "scalp_recovery_confirmation" in score
        ):
            missing.append("scalp_reversal_or_recovery_confirmation")
    elif lane == "SWING":
        lane_score = score.get("swing_score")
        if lane_score is None and not (
            source_mode == "SWING" and score.get("score") is not None
        ):
            missing.append("swing_score")
        if "swing_signal" not in score and source_mode != "SWING":
            missing.append("swing_signal")
    else:
        missing.append("supported_trade_mode")
    return missing


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
        owns_stream: bool = True,
        initial_cash: float,
        fee_rate: float,
        warmup_client: Any = None,
        scan_batch_size: int = 8,
        state_connect_factory: Any = None,
        outcome_connect_factory: Any = None,
    ) -> None:
        self.venue = venue
        self.stream = stream
        self.owns_stream = bool(owns_stream)
        self.requested_symbols = tuple(str(s).upper() for s in symbols)
        self.ticker_supported_symbols = self.requested_symbols if warmup_client is None else ()
        self.symbols = self.requested_symbols
        self.unsupported_symbols: tuple[str, ...] = ()
        self.warmup_incomplete_symbols: tuple[str, ...] = ()
        self.universe_ready = warmup_client is None
        self.warmup_error: str | None = None
        self.warmup_seeded_series = 0
        self.warmup_expected_series = len(self.symbols) * len(_INTERVALS)
        self.scan_batch_size = max(1, int(scan_batch_size))
        self.configured_scan_batch_size = self.scan_batch_size
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
        self.outcome_persistence_error: str | None = None
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
        # breadth; they must never read MAIN's Binance market snapshot.
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
        self.entry_captures = PostgresEvidenceStore(
            database_url,
            evidence_type=f"ENTRY_V2_CAPTURE_{venue}_HOSTED_LAB",
            max_records=2_000,
            connect_factory=outcome_connect_factory,
        )
        # Outcome writes are idempotent by position_id in Postgres. Do not
        # load the full historical outcome table into RAM during startup.
        # A duplicate append returns False without last_error and is treated
        # as already persisted by _persist_new_outcomes().
        self._reported_closed_ids: set[str] = set()
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
        # The Binance feed is owned by MAIN and is shared read-only with this
        # lab. Bybit and OKX streams are owned by their respective lab objects.
        if self.stream is not None and self.owns_stream:
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
        # Check the exchange's current public Spot ticker universe once. This
        # prevents one unsupported or delisted symbol from blocking breadth
        # readiness for the entire venue. No trading/private API is involved.
        try:
            listing = self.warmup_client.fetch_tickers(self.requested_symbols)
            supported = tuple(
                symbol
                for symbol in self.requested_symbols
                if isinstance(listing, Mapping)
                and isinstance(listing.get(symbol), Mapping)
                and float(listing[symbol].get("lastPrice") or 0.0) > 0.0
            )
        except Exception as exc:
            self.warmup_error = f"SYMBOL_PREFLIGHT_{type(exc).__name__}"
            self.last_error = self.warmup_error
            self.universe_ready = False
            logger.error(
                "[HOSTED-PAPER-LAB-PREFLIGHT] venue=%s failed=%s; new entries disabled",
                self.venue,
                self.warmup_error,
            )
            return

        self.ticker_supported_symbols = supported
        self.unsupported_symbols = tuple(
            symbol for symbol in self.requested_symbols if symbol not in set(supported)
        )
        self.warmup_expected_series = len(supported) * len(_INTERVALS)
        if not supported or "BTCUSDT" not in supported:
            self.symbols = ()
            self.warmup_error = "BTCUSDT_OR_SPOT_UNIVERSE_UNAVAILABLE"
            self.last_error = self.warmup_error
            self.universe_ready = False
            logger.error(
                "[HOSTED-PAPER-LAB-PREFLIGHT] venue=%s supported=%d/%d btc_available=%s; "
                "new entries disabled unsupported=%s",
                self.venue,
                len(supported),
                len(self.requested_symbols),
                "BTCUSDT" in supported,
                ",".join(self.unsupported_symbols),
            )
            return

        self.universe_ready = False
        if self.unsupported_symbols:
            logger.warning(
                "[HOSTED-PAPER-LAB-PREFLIGHT] venue=%s supported=%d/%d unsupported=%s",
                self.venue,
                len(supported),
                len(self.requested_symbols),
                ",".join(self.unsupported_symbols),
            )
        # One bounded cold-start seed per venue. After this, WebSocket updates
        # own the data; the runner never performs periodic REST polling.
        warm_symbols: list[str] = []
        incomplete_symbols: list[str] = []
        for symbol in self.ticker_supported_symbols:
            symbol_ready = True
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
                        symbol_ready = False
                except Exception as exc:
                    failed += 1
                    symbol_ready = False
                    logger.warning(
                        "[HOSTED-PAPER-LAB-WARMUP] venue=%s symbol=%s interval=%s error=%s",
                        self.venue,
                        symbol,
                        interval,
                        type(exc).__name__,
                    )
                time.sleep(0.15)
            if symbol_ready:
                warm_symbols.append(symbol)
            else:
                incomplete_symbols.append(symbol)

        self.symbols = tuple(warm_symbols)
        self.warmup_incomplete_symbols = tuple(incomplete_symbols)
        self.warmup_seeded_series = seeded
        self.warmup_expected_series = len(self.ticker_supported_symbols) * len(_INTERVALS)
        if failed:
            self.warmup_error = f"INCOMPLETE_COLD_START_HISTORY_{failed}_SERIES"
        self.universe_ready = bool(self.symbols) and "BTCUSDT" in self.symbols
        if not self.universe_ready:
            self.last_error = "BTCUSDT_HISTORY_NOT_READY"
            self.warmup_error = self.warmup_error or self.last_error
        logger.info(
            "[HOSTED-PAPER-LAB-WARMUP] venue=%s seeded_series=%d/%d incomplete=%d "
            "scoring_symbols=%d/%d unsupported=%s incomplete_symbols=%s",
            self.venue,
            seeded,
            self.warmup_expected_series,
            failed,
            len(self.symbols),
            len(self.ticker_supported_symbols),
            ",".join(self.unsupported_symbols) or "NONE",
            ",".join(self.warmup_incomplete_symbols) or "NONE",
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

    def _persist_candidate_capture(
        self,
        capture: Any,
        *,
        score: Mapping[str, Any],
        mode: str,
        entry_price: float,
        stop_loss: float,
        economics: Mapping[str, Any],
        decision: str,
        failed_gate: str | None = None,
        brain_record: Any = None,
        position_id: str | None = None,
    ) -> None:
        """Persist the candidate's exact Entry v2 and final Paper gate evidence."""
        brain = None
        if brain_record is not None:
            brain = {
                "allowed": bool(getattr(brain_record, "allowed", False)),
                "action": str(getattr(brain_record, "brain_action", "") or ""),
                "reason": str(getattr(brain_record, "brain_reason", "") or ""),
                "confidence": float(getattr(brain_record, "brain_confidence", 0.0) or 0.0),
            }
        record = capture.to_dict()
        record.update({
            "venue": self.venue,
            "venue_mode": f"{self.venue}_HOSTED_PAPER_LAB",
            "market_data_policy": f"ISOLATED_{self.venue}_WEBSOCKET",
            "observed_at": time.time(),
            "candidate": {
                "symbol": str(capture.symbol).upper(),
                "trade_mode": str(mode).upper(),
                "signal": "BUY",
                "score": (
                    score.get("scalp_score")
                    if str(mode).upper() == "SCALP"
                    else score.get("swing_score")
                ),
                "entry_price": float(entry_price),
                "stop_loss": float(stop_loss),
                "market_data_source": self.venue,
                "market_data_transport": "WEBSOCKET",
            },
            "entry_economics": dict(economics),
            "brain_authority": brain,
            "final_decision": str(decision),
            "failed_gate": failed_gate,
            "position_id": position_id,
        })
        try:
            inserted = self.entry_captures.append(record)
            if not inserted and self.entry_captures.last_error:
                logger.warning(
                    "[HOSTED-PAPER-LAB] entry evidence persistence failed venue=%s "
                    "symbol=%s error=%s",
                    self.venue,
                    capture.symbol,
                    self.entry_captures.last_error,
                )
        except Exception as exc:
            # Candidate evidence is diagnostic-only. It must never bypass or
            # change the Paper entry decision, Risk or execution outcome.
            logger.exception(
                "[HOSTED-PAPER-LAB] entry evidence writer raised venue=%s symbol=%s error=%s",
                self.venue,
                capture.symbol,
                type(exc).__name__,
            )

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
        missing_context = _lane_context_missing(score, mode)
        if missing_context:
            self._record_block("BRAIN_CONTEXT_INCOMPLETE")
            logger.warning(
                "[HOSTED-PAPER-LAB] entry blocked venue=%s symbol=%s mode=%s missing=%s",
                self.venue,
                symbol,
                mode,
                ",".join(missing_context),
            )
            return
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
        if len(btc_closed) < 3:
            self._record_block("BTC_GUARD_CONTEXT_UNAVAILABLE")
            return
        try:
            btc_received = float(btc_rows[-1].get("received_at") or 0.0)
        except (TypeError, ValueError, IndexError):
            btc_received = 0.0
        if btc_received <= 0.0 or time.time() - btc_received > 180.0:
            self._record_block("BTC_GUARD_CONTEXT_STALE")
            return
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
            failed_gate = str(economics.get("reason") or "ENTRY_ECONOMICS_REJECTED")
            self._persist_candidate_capture(
                capture,
                score=score,
                mode=mode,
                entry_price=price,
                stop_loss=stop_loss,
                economics=economics,
                decision="REJECTED_ENTRY_ECONOMICS",
                failed_gate=failed_gate,
            )
            self._record_block(failed_gate)
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
            failed_gate = str(brain_record.brain_reason or "BRAIN_REJECTED")
            self._persist_candidate_capture(
                capture,
                score=score,
                mode=mode,
                entry_price=price,
                stop_loss=stop_loss,
                economics=economics,
                decision="REJECTED_BRAIN_AUTHORITY",
                failed_gate=failed_gate,
                brain_record=brain_record,
            )
            self._record_block(failed_gate)
            return

        # Preserve the exact Entry v2 capture through the Trade Manager
        # lifecycle boundary so the closed Paper outcome can be joined to its
        # immutable candidate decision without relying on a later lookup.
        self.runtime.last_entry_diagnostics.setdefault(symbol, {})[
            "entry_v2_shadow"
        ] = v2_shadow
        # Keep a pre-entry rollback point. Paper Execution is synchronous;
        # a position is only counted as opened after the account and repository
        # snapshot is durably committed for this venue.
        pre_entry_account = self.adapter.export_snapshot()
        pre_entry_positions = self.repository.export_snapshot()
        pre_entry_orders = dict(getattr(self.adapter, "orders", {}) or {})
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
            failed_gate = str(trace.get("result") or "TRADE_MANAGER_REJECTED")
            self._persist_candidate_capture(
                capture,
                score=score,
                mode=mode,
                entry_price=price,
                stop_loss=stop_loss,
                economics=economics,
                decision="REJECTED_TRADE_MANAGER",
                failed_gate=failed_gate,
                brain_record=brain_record,
            )
            self._record_block(failed_gate)
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
        if not self._save_state(force=True):
            # Roll back the synchronous Paper fill if the account/position
            # state cannot be committed. Retry writing the pre-entry snapshot
            # to reconcile an uncertain commit result, and pause future entries
            # if even the rollback snapshot cannot be persisted.
            rollback_saved = self._rollback_unpersisted_entry(
                pre_entry_account,
                pre_entry_positions,
                pre_entry_orders,
            )
            if not rollback_saved:
                self.pause_new_entries = True
            self._persist_candidate_capture(
                capture,
                score=score,
                mode=mode,
                entry_price=price,
                stop_loss=stop_loss,
                economics=economics,
                decision="REJECTED_STATE_PERSISTENCE",
                failed_gate="PAPER_LAB_STATE_NOT_DURABLE",
                brain_record=brain_record,
            )
            self._record_block("PAPER_LAB_STATE_NOT_DURABLE")
            return

        self._persist_candidate_capture(
            capture,
            score=score,
            mode=mode,
            entry_price=price,
            stop_loss=stop_loss,
            economics=economics,
            decision="PAPER_POSITION_OPENED",
            brain_record=brain_record,
            position_id=str(position.position_id),
        )
        self.entry_allowed += 1
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
        active_positions = list(self.repository.get_open_positions())
        all_position_prices_fresh = True
        for position in active_positions:
            ticker = self.stream.get_latest_ticker(position.symbol)
            if not isinstance(ticker, Mapping) or not self._ticker_is_fresh(ticker, now):
                all_position_prices_fresh = False
                continue
            price = float(ticker.get("lastPrice") or 0.0)
            if price <= 0.0:
                all_position_prices_fresh = False
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
        if active_positions and all_position_prices_fresh:
            result = self.runtime.run_exit_watchdog()
            if (
                int(getattr(result, "closed", 0) or 0) > 0
                or int(getattr(result, "exit_signals", 0) or 0) > 0
            ):
                # Persist close, partial-close and hold/review state transitions
                # immediately; a restart must not restore an older lifecycle.
                self._save_state(force=True)
        elif active_positions:
            # Never execute an exit decision using a stale mark from a prior
            # venue event. Keep the position open until all of this lab's
            # active symbols have fresh prices again.
            self._record_block("EXIT_WATCHDOG_VENUE_PRICE_STALE")

    def _persist_new_outcomes(self) -> None:
        unresolved_error: str | None = None
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
                unresolved_error = str(self.outcomes.last_error)
                logger.error(
                    "[HOSTED-PAPER-LAB] outcome persistence failed venue=%s position=%s error=%s",
                    self.venue,
                    position_id,
                    unresolved_error,
                )
            else:
                # A prior append may have committed before a connection reset.
                self._reported_closed_ids.add(position_id)
        self.outcome_persistence_error = unresolved_error

        cutoff = time.time() - 40.0 * 24.0 * 60.0 * 60.0
        removed = self.repository.prune_terminal_positions(
            older_than_epoch=cutoff,
            persisted_closed_ids=self._reported_closed_ids,
        )
        if removed:
            # Keep the Part-6 daily/weekly/monthly counters aligned with the
            # retained 40-day closed-position window, and bound the id set.
            recent_closed_ids = {
                str(position.position_id)
                for position in self.repository.get_closed_positions()
            }
            self._reported_closed_ids.intersection_update(recent_closed_ids)
            self.runtime.loss_ledger.sync(self.repository.get_closed_positions())
            self._save_state(force=True)
            logger.info(
                "[HOSTED-PAPER-LAB] pruned old terminal positions venue=%s count=%d",
                self.venue,
                len(removed),
            )

    def _compact_order_history(self, *, keep: int = 1000) -> int:
        """Bound the in-memory synchronous Paper order cache.

        Filled/rejected Paper requests are complete at their execution
        boundary; active position and outcome records retain their own order
        identifiers, so old adapter response objects need not accumulate
        forever in this long-running hosted process.
        """
        orders = getattr(self.adapter, "orders", None)
        if not isinstance(orders, dict) or len(orders) <= keep:
            return 0
        retained = dict(list(orders.items())[-max(1, int(keep)):])
        removed = len(orders) - len(retained)
        orders.clear()
        orders.update(retained)
        return removed

    def _rollback_unpersisted_entry(
        self,
        account_snapshot: Mapping[str, Any],
        position_snapshot: Mapping[str, Any],
        order_snapshot: Mapping[str, Any],
    ) -> bool:
        """Restore the pre-entry Paper state when the entry snapshot cannot commit."""
        self.adapter.restore_snapshot(dict(account_snapshot))
        self.adapter.orders = dict(order_snapshot)
        self.repository.restore_snapshot(dict(position_snapshot))
        self.runtime.loss_ledger.sync(self.repository.get_closed_positions())
        return self._save_state(force=True)

    def _save_state(self, *, force: bool = False) -> bool:
        self._compact_order_history()
        now = time.time()
        if not force and now - self._last_state_save_at < 60.0:
            return self.persistence_error is None
        try:
            # A False return means the content hash was unchanged, not a
            # persistence error. A successful no-op is still durable.
            self.state.save(self.adapter, self.repository)
            self._last_state_save_at = now
            self.persistence_error = None
            return True
        except Exception as exc:
            self.persistence_error = f"{type(exc).__name__}: {exc}"
            logger.error(
                "[HOSTED-PAPER-LAB] state persistence blocked venue=%s error=%s",
                self.venue,
                self.persistence_error,
            )
            return False

    def process_cycle(
        self,
        now: float | None = None,
        *,
        scan_new_entries: bool = True,
    ) -> None:
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
            if not scan_new_entries or not self.universe_ready or not self.symbols:
                if not self.universe_ready:
                    self._record_block("VENUE_SPOT_UNIVERSE_NOT_READY")
                self._persist_new_outcomes()
                self._save_state()
                self.last_cycle_seconds = round(time.monotonic() - started, 4)
                return

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
                regime = (
                    derive_market_breadth(self.latest_scores).regime
                    if breadth_ready else "TRANSITION"
                )
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
                        if self.outcome_persistence_error:
                            self._record_block("PAPER_OUTCOME_NOT_DURABLE")
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
            "requested_symbols": len(self.requested_symbols),
            "ticker_supported_symbols": list(self.ticker_supported_symbols),
            "supported_symbol_count": len(self.ticker_supported_symbols),
            "scoring_symbols": list(self.symbols),
            "scoring_symbol_count": len(self.symbols),
            "unsupported_symbols": list(self.unsupported_symbols),
            "warmup_incomplete_symbols": list(self.warmup_incomplete_symbols),
            "universe_ready": self.universe_ready,
            "warmup_seeded_series": self.warmup_seeded_series,
            "warmup_expected_series": self.warmup_expected_series,
            "warmup_error": self.warmup_error,
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
            "outcome_persistence_error": self.outcome_persistence_error,
            "entry_capture_retention_limit": self.entry_captures.max_records,
        }

    def close(self) -> None:
        if self.stream is not None and self.owns_stream:
            self.stream.stop()
        self.state.close()
        self.outcomes.close()
        self.entry_captures.close()


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
        connect_factory: Any = None,
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
        self._cpu_time_last = time.process_time()
        self._wall_time_last = time.monotonic()
        self._cpu_load_percent = 0.0
        self._cpu_hot_cycles = 0
        self._cpu_cool_cycles = 0
        self._cpu_guard_paused = False
        self._cpu_scan_throttled = False
        self.labs: dict[str, _VenueLab] = {}
        try:
            self.labs["BINANCE"] = _VenueLab(
                venue="BINANCE",
                stream=binance_stream,
                symbols=symbols,
                database_url=database_url,
                owns_stream=False,
                initial_cash=initial_cash,
                fee_rate=fee_rate,
                scan_batch_size=scan_batch_size,
                state_connect_factory=connect_factory,
                outcome_connect_factory=connect_factory,
            )
            self._sample_startup_memory("BINANCE")
            self.labs["BYBIT"] = _VenueLab(
                venue="BYBIT",
                stream=bybit_stream,
                symbols=symbols,
                database_url=database_url,
                initial_cash=initial_cash,
                fee_rate=fee_rate,
                warmup_client=bybit_client,
                scan_batch_size=scan_batch_size,
                state_connect_factory=connect_factory,
                outcome_connect_factory=connect_factory,
            )
            self._sample_startup_memory("BYBIT")
            self.labs["OKX"] = _VenueLab(
                venue="OKX",
                stream=okx_stream,
                symbols=symbols,
                database_url=database_url,
                initial_cash=initial_cash,
                fee_rate=fee_rate,
                warmup_client=okx_client,
                scan_batch_size=scan_batch_size,
                state_connect_factory=connect_factory,
                outcome_connect_factory=connect_factory,
            )
            self._sample_startup_memory("OKX")
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

    def _sample_startup_memory(self, venue: str) -> None:
        self._max_memory_mb = max(self._max_memory_mb, self._memory_mb())
        if self._max_memory_mb >= 400.0:
            raise RuntimeError(
                f"hosted labs startup memory guard after {venue}: "
                f"{self._max_memory_mb:.1f} MB"
            )

    def start(self) -> None:
        if not self.enabled:
            return
        for venue in _SUPPORTED_VENUES:
            self.labs[venue].start()
            self._sample_startup_memory(f"{venue}_WEBSOCKET_START")
            if self._last_memory_guard():
                for lab in self.labs.values():
                    lab.pause_new_entries = True
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
            # Manage open positions and rescore a small rotating symbol
            # batch on every venue each MAIN cycle. With the normal 30-second
            # MAIN loop and four symbols per venue, the full 22-symbol universe
            # is revisited about every three minutes per venue.
            for venue in _SUPPORTED_VENUES:
                lab = self.labs[venue]
                try:
                    lab.process_cycle(scan_new_entries=True)
                except Exception as exc:
                    lab.last_error = f"{type(exc).__name__}: {exc}"
                    logger.exception("[HOSTED-PAPER-LAB] cycle failed venue=%s", venue)
            self._cycles += 1
            self._last_cycle_seconds = round(time.monotonic() - started, 4)
            self._max_memory_mb = max(self._max_memory_mb, self._memory_mb())

            # Render Free provides a small shared CPU allowance. Throttle
            # shadow scoring before it can starve the authoritative MAIN loop.
            cpu_now = time.process_time()
            wall_now = time.monotonic()
            wall_delta = max(0.001, wall_now - self._wall_time_last)
            cpu_delta = max(0.0, cpu_now - self._cpu_time_last)
            self._cpu_time_last = cpu_now
            self._wall_time_last = wall_now
            self._cpu_load_percent = round((cpu_delta / wall_delta) / 0.10 * 100.0, 2)
            if self._cpu_load_percent >= 80.0:
                self._cpu_hot_cycles += 1
                self._cpu_cool_cycles = 0
            elif self._cpu_load_percent <= 55.0:
                self._cpu_cool_cycles += 1
                self._cpu_hot_cycles = 0
            else:
                self._cpu_hot_cycles = 0
                self._cpu_cool_cycles = 0

            if self._cpu_hot_cycles >= 3 and not self._cpu_scan_throttled:
                self._cpu_scan_throttled = True
                for lab in self.labs.values():
                    lab.scan_batch_size = 1
                logger.error(
                    "[HOSTED-PAPER-LABS] CPU guard throttled scan batch to 1 load=%.1f%%",
                    self._cpu_load_percent,
                )
            if self._cpu_hot_cycles >= 6 and not self._cpu_guard_paused:
                self._cpu_guard_paused = True
                for lab in self.labs.values():
                    lab.pause_new_entries = True
                logger.error(
                    "[HOSTED-PAPER-LABS] CPU guard paused new lab entries load=%.1f%%",
                    self._cpu_load_percent,
                )
            if self._cpu_cool_cycles >= 8 and not self._last_memory_guard():
                if self._cpu_scan_throttled:
                    for lab in self.labs.values():
                        lab.scan_batch_size = lab.configured_scan_batch_size
                    self._cpu_scan_throttled = False
                if self._cpu_guard_paused:
                    for lab in self.labs.values():
                        lab.pause_new_entries = False
                    self._cpu_guard_paused = False

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
            "estimated_free_cpu_load_percent": self._cpu_load_percent,
            "cpu_scan_throttled": self._cpu_scan_throttled,
            "cpu_guard_paused": self._cpu_guard_paused,
            "entry_scan_venues": list(_SUPPORTED_VENUES) if self._cycles else [],
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
