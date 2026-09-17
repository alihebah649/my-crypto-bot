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


@dataclass
class EntryV2RuntimeCapture:
    legacy: Any
    runtime: Any
    mtf_candles: Mapping[str, Mapping[str, list[dict]]]
    trading_symbols: list[str]
    btc_guard_provider: Callable[[], Mapping[str, Any]] | None = None
    mtf_candles_provider: Callable[[], Mapping[str, Mapping[str, list[dict]]]] | None = None
    capture_store: EntryV2CaptureStore | None = None
    max_history: int = 500
    _original_fetch_strategy_data: Callable[[], Any] | None = field(default=None, init=False)
    _original_score_symbol: Callable[..., Any] | None = field(default=None, init=False)
    _original_repository_add: Callable[..., Any] | None = field(default=None, init=False)
    _last_tickers: dict[str, dict] = field(default_factory=dict, init=False)
    _last_candles_15m: dict[str, list[dict]] = field(default_factory=dict, init=False)
    _last_candles_5m: dict[str, list[dict]] = field(default_factory=dict, init=False)
    _latest: dict[str, EntryV2ShadowCapture] = field(default_factory=dict, init=False)
    _history: list[EntryV2ShadowCapture] = field(default_factory=list, init=False)
    _cycle_captured_symbols: set[str] = field(default_factory=set, init=False)
    _cycle_count: int = 0

    def __post_init__(self) -> None:
        if self.capture_store is None:
            persistence_dir = getattr(self.runtime, "persistence_dir", None)
            if persistence_dir:
                path = Path(persistence_dir) / "entry_v2_shadow" / "captures.jsonl"
                self.capture_store = EntryV2CaptureStore(path)

    def install(self) -> "EntryV2RuntimeCapture":
        if self._original_fetch_strategy_data is not None:
            return self
        self._original_fetch_strategy_data = self.legacy.fetch_strategy_data
        self._original_score_symbol = getattr(self.legacy, "score_symbol", None)

        def _capture_fetch():
            self._cycle_count += 1
            self._cycle_captured_symbols.clear()
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
                    capture = self._latest.get(symbol)
                    if capture is not None:
                        metadata = getattr(position, "entry_metadata", None)
                        if isinstance(metadata, dict):
                            metadata.setdefault("entry_v2_shadow_capture_id", capture.capture_id)
                            metadata.setdefault("entry_v2_shadow_capture_at", capture.captured_at)
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

    def capture_candidate(self, symbol: str, legacy_result: Mapping[str, Any]) -> EntryV2ShadowCapture | None:
        """Capture one scored BUY candidate immediately before legacy execution."""
        if not isinstance(legacy_result, Mapping) or not self._is_candidate(legacy_result):
            return None
        normalized = str(symbol).upper()
        candles_15m = self._last_candles_15m.get(normalized, []) or self._last_candles_15m.get(symbol, []) or []
        candles_5m = self._last_candles_5m.get(normalized, []) or self._last_candles_5m.get(symbol, []) or []
        ticker = self._last_tickers.get(normalized, {}) or self._last_tickers.get(symbol, {}) or {}
        current_mtf = self._current_mtf_candles()
        context = current_mtf.get(normalized, {}) or current_mtf.get(symbol, {}) or {}
        candles_1h = context.get("1h", []) or []
        candles_4h = context.get("4h", []) or []

        price = float(legacy_result.get("price", ticker.get("lastPrice", 0.0)) or 0.0)
        atr = float(legacy_result.get("atr", 0.0) or 0.0)
        stop_loss = price - (2.0 * atr) if price > 0 and atr > 0 else 0.0
        stop_distance_percent = (2.0 * atr / price * 100.0) if price > 0 and atr > 0 else 0.0
        bid = float(ticker.get("bidPrice", price) or price)
        ask = float(ticker.get("askPrice", price) or price)
        spread_percent = ((ask - bid) / price * 100.0) if price > 0 else 0.0

        mode = str(legacy_result.get("trade_mode", "NONE") or "NONE").upper()
        if mode not in {"SCALP", "SWING"}:
            mode = "SCALP" if legacy_result.get("scalp_signal") == "BUY" else "SWING"

        target_rr = calculate_target_rr(
            trade_mode=mode,
            entry_price=price,
            stop_loss=stop_loss,
            candles_by_timeframe={"5m": candles_5m, "15m": candles_15m, "1h": candles_1h, "4h": candles_4h},
        )

        facts = EntryV2MarketFacts(
            legacy_result=legacy_result,
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
            btc_guard="REJECT" if bool((self.btc_guard_provider() if self.btc_guard_provider else {}).get("crashing")) else "PASS",
        )
        capture = capture_entry_v2(normalized, facts)
        self._latest[normalized] = capture
        self._cycle_captured_symbols.add(normalized)
        self._history.append(capture)
        return capture

    def capture_cycle(self) -> dict[str, Any]:
        """Capture the just-completed scan; never alter its execution result."""
        cycle_records: dict[str, EntryV2ShadowCapture] = {}
        for symbol, legacy_result in (getattr(self.legacy, "latest_scores", {}) or {}).items():
            if not self._is_candidate(legacy_result):
                continue
            normalized = str(symbol).upper()
            if normalized in self._cycle_captured_symbols:
                continue
            capture = self.capture_candidate(normalized, legacy_result)
            if capture is not None:
                cycle_records[normalized] = capture

        if not cycle_records:
            cycle_records = {
                symbol: capture
                for symbol, capture in self._latest.items()
                if symbol in self._cycle_captured_symbols
            }

        if len(self._history) > self.max_history:
            del self._history[:-self.max_history]

        persisted = 0
        if self.capture_store is not None and cycle_records:
            try:
                persisted = self.capture_store.append_many(capture.to_dict() for capture in cycle_records.values())
            except Exception as exc:
                self.capture_store.last_error = f"{type(exc).__name__}: {exc}"
                self.runtime.last_entry_diagnostics.setdefault("__entry_v2_shadow__", {})["persistence_error"] = str(exc)
        summary = self.summary(cycle_records)
        summary["persisted_records"] = persisted
        summary["persistent_total_records"] = self.capture_store.count() if self.capture_store is not None else 0
        summary["persistent_store_error"] = self.capture_store.last_error if self.capture_store is not None else None
        return summary

    def summary(self, cycle_records: Mapping[str, EntryV2ShadowCapture] | None = None) -> dict[str, Any]:
        records = list(cycle_records.values()) if cycle_records is not None else list(self._latest.values())
        legacy_rows = list((getattr(self.legacy, "latest_scores", {}) or {}).values())
        approved = sum(1 for item in records if item.v2_decision.get("approved") is True)
        rejected = sum(1 for item in records if item.v2_decision.get("approved") is False)
        return {
            "schema_version": 2,
            "cycle": self._cycle_count,
            "evaluated_symbols": len(legacy_rows),
            "legacy_buy_candidates": sum(1 for row in legacy_rows if self._is_candidate(row)),
            "captured_candidates": len(records),
            "v2_approved": approved,
            "v2_rejected": rejected,
            "v2_reward_risk_pending": sum(1 for item in records if item.v2_decision.get("failed_gate") == "REWARD_RISK_PENDING"),
            "v2_no_target_above_entry": sum(1 for item in records if item.entry_scenario.get("risk", {}).get("target_status") == "NO_TARGET_ABOVE_ENTRY"),
            "v2_no_target_meets_rr": sum(1 for item in records if item.entry_scenario.get("risk", {}).get("target_status") == "NO_TARGET_MEETS_RR"),
            "latest": {
                symbol: {
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
                for symbol, item in self._latest.items()
            },
        }

    def latest_capture_id(self, symbol: str) -> str | None:
        capture = self._latest.get(str(symbol).upper())
        return capture.capture_id if capture is not None else None

    def latest_captures(self) -> dict[str, dict[str, Any]]:
        return {symbol: capture.to_dict() for symbol, capture in self._latest.items()}


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
    capture = EntryV2RuntimeCapture(
        legacy=legacy,
        runtime=runtime,
        mtf_candles=mtf_candles,
        trading_symbols=list(trading_symbols),
        btc_guard_provider=btc_guard_provider,
        mtf_candles_provider=mtf_candles_provider,
        capture_store=capture_store,
        max_history=max_history,
    )
    return capture.install()
