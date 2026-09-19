"""Attach Entry v2 shadow capture to the existing Paper scan without execution authority.

This module is deliberately an orchestration boundary. It observes the already
active legacy scoring call before execution, keeps the exact in-cycle
observations, and exposes a cycle capture method. It never changes the legacy
decision and never vetoes, sizes, or executes trades.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import sys
from typing import Any, Callable, Mapping

from .entry_target_rr import calculate_target_rr
from .entry_v2_adapter import EntryV2MarketFacts
from .entry_v2_capture import EntryV2ShadowCapture, capture_entry_v2, capture_summary
from .entry_v2_capture_store import EntryV2CaptureStore
from .entry_v2_outcome_analysis import analyze_entry_v2_outcomes
from .entry_v2_shadow_report import build_entry_v2_shadow_report


@dataclass
class EntryV2RuntimeCapture:
    legacy: Any
    runtime: Any
    mtf_candles: Mapping[str, Mapping[str, list[dict]]]
    trading_symbols: list[str]
    btc_guard_provider: Callable[[], Mapping[str, Any]] | None = None
    mtf_candles_provider: Callable[[], Mapping[str, Mapping[str, list[dict]]]] | None = None
    capture_store: EntryV2CaptureStore | None = None
    brain_shadow_store: Any | None = None
    max_history: int = 500
    _original_fetch_strategy_data: Callable[[], Any] | None = field(default=None, init=False)
    _original_score_symbol: Callable[..., Any] | None = field(default=None, init=False)
    _original_repository_add: Callable[..., Any] | None = field(default=None, init=False)
    _last_tickers: dict[str, dict] = field(default_factory=dict, init=False)
    _last_candles_15m: dict[str, list[dict]] = field(default_factory=dict, init=False)
    _last_candles_5m: dict[str, list[dict]] = field(default_factory=dict, init=False)
    # Keep the symbol-level view for compatibility, plus an explicit lane index
    # so SCALP/SWING captures never share one identity.
    _latest: dict[str, EntryV2ShadowCapture] = field(default_factory=dict, init=False)
    _latest_by_mode: dict[tuple[str, str], EntryV2ShadowCapture] = field(default_factory=dict, init=False)
    _history: list[EntryV2ShadowCapture] = field(default_factory=list, init=False)
    _cycle_captured_keys: set[tuple[str, str]] = field(default_factory=set, init=False)
    _cycle_persisted_keys: set[tuple[str, str]] = field(default_factory=set, init=False)
    _cycle_count: int = 0

    def __post_init__(self) -> None:
        if self.capture_store is None:
            persistence_dir = getattr(self.runtime, "persistence_dir", None)
            if persistence_dir:
                path = Path(persistence_dir) / "entry_v2_shadow" / "captures.jsonl"
                self.capture_store = EntryV2CaptureStore(path)
        if self.brain_shadow_store is None:
            self.brain_shadow_store = getattr(self.runtime, "brain_shadow_store", None)

    def install(self) -> "EntryV2RuntimeCapture":
        if self._original_fetch_strategy_data is not None:
            return self
        self._original_fetch_strategy_data = self.legacy.fetch_strategy_data
        self._original_score_symbol = getattr(self.legacy, "score_symbol", None)

        def _capture_fetch():
            self._cycle_count += 1
            self._cycle_captured_keys.clear()
            self._cycle_persisted_keys.clear()
            data = self._original_fetch_strategy_data()
            try:
                tickers, candles_15m, candles_5m = data
                self._last_tickers = dict(tickers or {})
                self._last_candles_15m = dict(candles_15m or {})
                self._last_candles_5m = dict(candles_5m or {})
            except (TypeError, ValueError):
                self._last_tickers = {}
                self._last_candles_15m = {}
                self._last_candles_5m = {}
            return data

        self.legacy.fetch_strategy_data = _capture_fetch

        if callable(self._original_score_symbol):
            def _capture_score(symbol: str, *args: Any, **kwargs: Any):
                result = self._original_score_symbol(symbol, *args, **kwargs)
                try:
                    if isinstance(result, Mapping):
                        if result.get("scalp_signal") == "BUY":
                            self.capture_candidate(symbol, result, trade_mode="SCALP")
                        if result.get("swing_signal") == "BUY":
                            self.capture_candidate(symbol, result, trade_mode="SWING")
                        elif result.get("scalp_signal") != "BUY" and result.get("signal") == "BUY":
                            self.capture_candidate(symbol, result)
                    else:
                        self.capture_candidate(symbol, result)
                except Exception as exc:
                    self.runtime.last_entry_diagnostics.setdefault("__entry_v2_shadow__", {})["pre_execution_capture_error"] = str(exc)
                return result

            self.legacy.score_symbol = _capture_score

        repository = getattr(self.runtime, "repository", None)
        if repository is not None and callable(getattr(repository, "add", None)):
            self._original_repository_add = repository.add

            def _add_with_entry_v2_identity(position: Any):
                try:
                    symbol = str(getattr(position, "symbol", "")).upper()
                    metadata = getattr(position, "entry_metadata", None)
                    lane = ""
                    if isinstance(metadata, dict):
                        lane = str(metadata.get("trade_mode", "") or "").upper()
                    if lane not in {"SCALP", "SWING"}:
                        lane = str(getattr(position, "trade_mode", "") or "").upper()

                    capture = None
                    if lane in {"SCALP", "SWING"}:
                        key = (symbol, lane)
                        if key in self._cycle_captured_keys:
                            capture = self._latest_by_mode.get(key)
                    elif any(key[0] == symbol for key in self._cycle_captured_keys):
                        # Compatibility fallback for callers that do not expose
                        # lane identity at repository insertion time.
                        capture = self._latest.get(symbol)

                    if capture is not None and isinstance(metadata, dict):
                        metadata.setdefault("entry_v2_shadow_capture_id", capture.capture_id)
                        metadata.setdefault("entry_v2_shadow_capture_at", capture.captured_at)
                        metadata.setdefault("entry_v2_shadow_candidate_cycle", self._cycle_count)
                        metadata.setdefault("entry_v2_shadow_trade_mode", capture.v2_decision.get("trade_mode"))
                        metadata.setdefault("entry_v2_shadow_decision", dict(capture.v2_decision))
                        metadata.setdefault("entry_v2_shadow_target_price", capture.entry_scenario.get("risk", {}).get("target_price"))
                        metadata.setdefault("entry_v2_shadow_reward_risk", capture.entry_scenario.get("risk", {}).get("reward_risk"))
                        metadata.setdefault("entry_v2_shadow_target_status", capture.entry_scenario.get("risk", {}).get("target_status"))
                except Exception as exc:
                    self.runtime.last_entry_diagnostics.setdefault("__entry_v2_shadow__", {})["position_identity_error"] = str(exc)
                return self._original_repository_add(position)

            repository.add = _add_with_entry_v2_identity

        return self

    def _current_mtf_candles(self) -> Mapping[str, Mapping[str, list[dict]]]:
        if self.mtf_candles_provider is not None:
            try:
                return self.mtf_candles_provider() or {}
            except Exception:
                return {}
        main_module = sys.modules.get("__main__")
        live = getattr(main_module, "_mtf_candles", None) if main_module is not None else None
        if isinstance(live, Mapping):
            return live
        return self.mtf_candles or {}

    @staticmethod
    def _is_candidate(legacy_result: Mapping[str, Any]) -> bool:
        return bool(
            legacy_result.get("signal") == "BUY"
            or legacy_result.get("scalp_signal") == "BUY"
            or legacy_result.get("swing_signal") == "BUY"
        )

    def capture_candidate(
        self,
        symbol: str,
        legacy_result: Mapping[str, Any],
        *,
        trade_mode: str | None = None,
    ) -> EntryV2ShadowCapture | None:
        """Capture and persist one lane-specific BUY candidate before execution."""
        if not isinstance(legacy_result, Mapping) or not self._is_candidate(legacy_result):
            return None

        normalized = str(symbol).upper()
        requested_mode = str(trade_mode or "").upper()

        if requested_mode in {"SCALP", "SWING"}:
            if legacy_result.get(f"{requested_mode.lower()}_signal") != "BUY":
                return None
        else:
            requested_mode = str(legacy_result.get("trade_mode", "NONE") or "NONE").upper()
            if requested_mode not in {"SCALP", "SWING"}:
                requested_mode = "SCALP" if legacy_result.get("scalp_signal") == "BUY" else "SWING"

        cycle_key = (normalized, requested_mode)
        if cycle_key in self._cycle_captured_keys:
            return self._latest_by_mode.get(cycle_key) or self._latest.get(normalized)

        # Freeze this lane's score/signal/mode. A dual-lane candidate therefore
        # gets two independent Entry v2 observations and two capture IDs.
        lane_result = dict(legacy_result)
        lane_result["trade_mode"] = requested_mode
        lane_result["signal"] = "BUY"
        if requested_mode == "SCALP":
            if legacy_result.get("scalp_score") is not None:
                lane_result["score"] = legacy_result.get("scalp_score")
        else:
            if legacy_result.get("swing_score") is not None:
                lane_result["score"] = legacy_result.get("swing_score")

        candles_15m = (
            self._last_candles_15m.get(normalized, [])
            or self._last_candles_15m.get(symbol, [])
            or []
        )
        candles_5m = (
            self._last_candles_5m.get(normalized, [])
            or self._last_candles_5m.get(symbol, [])
            or []
        )
        ticker = (
            self._last_tickers.get(normalized, {})
            or self._last_tickers.get(symbol, {})
            or {}
        )
        current_mtf = self._current_mtf_candles()
        context = current_mtf.get(normalized, {}) or current_mtf.get(symbol, {}) or {}
        candles_1h = context.get("1h", []) or []
        candles_4h = context.get("4h", []) or []

        price = float(lane_result.get("price", ticker.get("lastPrice", 0.0)) or 0.0)
        atr = float(lane_result.get("atr", 0.0) or 0.0)
        stop_loss = price - (2.0 * atr) if price > 0 and atr > 0 else 0.0
        stop_distance_percent = (2.0 * atr / price * 100.0) if price > 0 and atr > 0 else 0.0
        bid = float(ticker.get("bidPrice", price) or price)
        ask = float(ticker.get("askPrice", price) or price)
        spread_percent = ((ask - bid) / price * 100.0) if price > 0 else 0.0

        target_rr = calculate_target_rr(
            trade_mode=requested_mode,
            entry_price=price,
            stop_loss=stop_loss,
            candles_by_timeframe={
                "5m": candles_5m,
                "15m": candles_15m,
                "1h": candles_1h,
                "4h": candles_4h,
            },
        )

        facts = EntryV2MarketFacts(
            legacy_result=lane_result,
            candles_5m=candles_5m,
            candles_15m=candles_15m,
            candles_1h=candles_1h,
            candles_4h=candles_4h,
            stop_distance_percent=stop_distance_percent,
            reward_risk=target_rr.reward_risk if target_rr.status == "VALID" else None,
            spread_percent=spread_percent,
            target_price=target_rr.target_price,
            target_source=target_rr.target_source,
            target_status=target_rr.status,
            btc_guard=(
                "REJECT"
                if bool(
                    (self.btc_guard_provider() if self.btc_guard_provider else {}).get(
                        "crashing"
                    )
                )
                else "PASS"
            ),
        )
        capture = capture_entry_v2(normalized, facts)
        self._latest[normalized] = capture
        self._latest_by_mode[cycle_key] = capture
        self._cycle_captured_keys.add(cycle_key)
        self._history.append(capture)

        summary = capture_summary(capture)
        diagnostics = self.runtime.last_entry_diagnostics.setdefault(
            normalized, {"symbol": normalized}
        )
        by_mode = diagnostics.setdefault("entry_v2_shadow_by_mode", {})
        by_mode[requested_mode] = summary
        # Keep the old field for compatibility; the by-mode field is the
        # authoritative source whenever both lanes exist.
        diagnostics["entry_v2_shadow"] = summary

        if self.capture_store is not None:
            try:
                persisted = self.capture_store.append(capture.to_dict())
                if persisted:
                    self._cycle_persisted_keys.add(cycle_key)
                else:
                    diagnostics = self.runtime.last_entry_diagnostics.setdefault(
                        "__entry_v2_shadow__", {}
                    )
                    diagnostics["persistence_error"] = self.capture_store.last_error
            except Exception as exc:
                self.capture_store.last_error = f"{type(exc).__name__}: {exc}"
                diagnostics = self.runtime.last_entry_diagnostics.setdefault(
                    "__entry_v2_shadow__", {}
                )
                diagnostics["persistence_error"] = str(exc)
        return capture

    def capture_cycle(self) -> dict[str, Any]:
        """Finalize the just-completed scan; never alter its execution result."""
        cycle_records: dict[str, EntryV2ShadowCapture] = {
            f"{symbol}|{mode}": self._latest_by_mode[(symbol, mode)]
            for symbol, mode in self._cycle_captured_keys
            if (symbol, mode) in self._latest_by_mode
        }

        for symbol, legacy_result in (getattr(self.legacy, "latest_scores", {}) or {}).items():
            if not self._is_candidate(legacy_result):
                continue
            normalized = str(symbol).upper()
            candidate_modes = []
            if legacy_result.get("scalp_signal") == "BUY":
                candidate_modes.append("SCALP")
            if legacy_result.get("swing_signal") == "BUY":
                candidate_modes.append("SWING")
            if not candidate_modes:
                candidate_modes = [str(legacy_result.get("trade_mode", "NONE") or "NONE").upper()]

            for mode in candidate_modes:
                cycle_key = (normalized, mode)
                if cycle_key in self._cycle_captured_keys:
                    continue
                capture = self.capture_candidate(normalized, legacy_result, trade_mode=mode)
                if capture is not None:
                    cycle_records[f"{normalized}|{mode}"] = capture

        if len(self._history) > self.max_history:
            del self._history[:-self.max_history]

        summary = self.summary(cycle_records)
        summary["persisted_records"] = len(self._cycle_persisted_keys)
        summary["persistent_total_records"] = (
            self.capture_store.count() if self.capture_store is not None else 0
        )
        summary["persistent_store_error"] = (
            self.capture_store.last_error if self.capture_store is not None else None
        )
        return summary

    def _repository_positions(self) -> list[Any]:
        repository = getattr(self.runtime, "repository", None)
        if repository is None:
            return []
        positions: list[Any] = []
        for method_name in ("get_open_positions", "get_closed_positions"):
            method = getattr(repository, method_name, None)
            if callable(method):
                try:
                    positions.extend(list(method() or []))
                except Exception:
                    continue
        return positions

    def _historical_snapshot(self) -> tuple[list[dict[str, Any]], list[Any]] | None:
        if self.capture_store is None or getattr(self.runtime, "repository", None) is None:
            return None
        try:
            return self.capture_store.read_all(), self._repository_positions()
        except Exception:
            return None

    def _historical_analysis(self) -> dict[str, Any]:
        snapshot = self._historical_snapshot()
        if snapshot is None:
            return {"historical_outcomes": None, "shadow_report": None}
        captures, positions = snapshot
        brain_records = []
        if self.brain_shadow_store is not None:
            try:
                brain_records = self.brain_shadow_store.read_all()
            except Exception:
                brain_records = []
        try:
            outcomes = analyze_entry_v2_outcomes(captures, positions)
        except Exception as exc:
            outcomes = {"schema_version": 1, "error": f"{type(exc).__name__}: {exc}"}
        try:
            shadow_report = build_entry_v2_shadow_report(
                captures,
                positions,
                brain_records=brain_records,
            )
        except Exception as exc:
            shadow_report = {"schema_version": 1, "error": f"{type(exc).__name__}: {exc}"}
        return {"historical_outcomes": outcomes, "shadow_report": shadow_report}

    def summary(self, cycle_records: Mapping[str, EntryV2ShadowCapture] | None = None) -> dict[str, Any]:
        records = (
            list(cycle_records.values())
            if cycle_records is not None
            else list(self._latest_by_mode.values())
        )
        legacy_rows = list((getattr(self.legacy, "latest_scores", {}) or {}).values())
        approved = sum(1 for item in records if item.v2_decision.get("approved") is True)
        rejected = sum(1 for item in records if item.v2_decision.get("approved") is False)
        historical = self._historical_analysis()

        def _compact(item: EntryV2ShadowCapture) -> dict[str, Any]:
            return {
                "capture_id": item.capture_id,
                "legacy_signal": item.legacy_result.get("signal"),
                "legacy_trade_mode": item.legacy_result.get("trade_mode"),
                "v2_decision": item.v2_decision.get("decision"),
                "v2_trade_mode": item.v2_decision.get("trade_mode"),
                "v2_setup_type": item.v2_decision.get("setup_type"),
                "v2_failed_gate": item.v2_decision.get("failed_gate"),
                "target_price": item.entry_scenario.get("risk", {}).get("target_price"),
                "target_source": item.entry_scenario.get("risk", {}).get("target_source"),
                "target_status": item.entry_scenario.get("risk", {}).get("target_status"),
                "reward_risk": item.entry_scenario.get("risk", {}).get("reward_risk"),
            }

        return {
            "schema_version": 2,
            "cycle": self._cycle_count,
            "evaluated_symbols": len(legacy_rows),
            "legacy_buy_candidates": sum(
                1 for row in legacy_rows if self._is_candidate(row)
            ),
            "captured_candidates": len(records),
            "v2_approved": approved,
            "v2_rejected": rejected,
            "v2_reward_risk_pending": sum(
                1
                for item in records
                if item.v2_decision.get("failed_gate") == "REWARD_RISK_PENDING"
            ),
            "v2_no_target_above_entry": sum(
                1
                for item in records
                if item.entry_scenario.get("risk", {}).get("target_status")
                == "NO_TARGET_ABOVE_ENTRY"
            ),
            "v2_no_target_meets_rr": sum(
                1
                for item in records
                if item.entry_scenario.get("risk", {}).get("target_status")
                == "NO_TARGET_MEETS_RR"
            ),
            "historical_outcomes": historical["historical_outcomes"],
            "shadow_report": historical["shadow_report"],
            "latest": {
                symbol: _compact(item) for symbol, item in self._latest.items()
            },
            "latest_by_mode": {
                f"{symbol}|{mode}": _compact(item)
                for (symbol, mode), item in self._latest_by_mode.items()
            },
        }

    def latest_capture_id(self, symbol: str, trade_mode: str | None = None) -> str | None:
        normalized = str(symbol).upper()
        if trade_mode:
            capture = self._latest_by_mode.get((normalized, str(trade_mode).upper()))
        else:
            capture = self._latest.get(normalized)
        return capture.capture_id if capture is not None else None

    def latest_captures(self) -> dict[str, dict[str, Any]]:
        return {symbol: capture.to_dict() for symbol, capture in self._latest.items()}

    def latest_captures_by_mode(self) -> dict[str, dict[str, Any]]:
        return {
            f"{symbol}|{mode}": capture.to_dict()
            for (symbol, mode), capture in self._latest_by_mode.items()
        }

    def persistent_records(self) -> list[dict[str, Any]]:
        return self.capture_store.read_all() if self.capture_store is not None else []


def install(
    *,
    legacy: Any,
    runtime: Any,
    mtf_candles: Mapping[str, Mapping[str, list[dict]]],
    trading_symbols: list[str],
    btc_guard_provider: Callable[[], Mapping[str, Any]] | None = None,
    mtf_candles_provider: Callable[[], Mapping[str, Mapping[str, list[dict]]]] | None = None,
    capture_store: EntryV2CaptureStore | None = None,
    max_history: int = 500,
) -> EntryV2RuntimeCapture:
    """Create and install a non-authoritative Entry v2 runtime shadow observer."""
    return EntryV2RuntimeCapture(
        legacy=legacy,
        runtime=runtime,
        mtf_candles=mtf_candles,
        trading_symbols=trading_symbols,
        btc_guard_provider=btc_guard_provider,
        mtf_candles_provider=mtf_candles_provider,
        capture_store=capture_store,
        max_history=max_history,
    ).install()


__all__ = ["EntryV2RuntimeCapture", "install"]
