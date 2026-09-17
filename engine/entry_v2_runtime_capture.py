"""Attach Entry v2 shadow capture to the existing Paper scan without execution authority.

This module is deliberately an orchestration boundary. It wraps the already
active legacy market-data fetch once, keeps the exact in-cycle observations,
and exposes a cycle capture method. It never changes the legacy decision or
opens/closes positions.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from .entry_v2_adapter import EntryV2MarketFacts
from .entry_v2_capture import EntryV2ShadowCapture, capture_entry_v2, capture_summary


@dataclass
class EntryV2RuntimeCapture:
    legacy: Any
    runtime: Any
    mtf_candles: Mapping[str, Mapping[str, list[dict]]]
    trading_symbols: list[str]
    btc_guard_provider: Callable[[], Mapping[str, Any]] | None = None
    max_history: int = 500
    _original_fetch_strategy_data: Callable[[], Any] | None = field(default=None, init=False)
    _last_tickers: dict[str, dict] = field(default_factory=dict, init=False)
    _last_candles_15m: dict[str, list[dict]] = field(default_factory=dict, init=False)
    _last_candles_5m: dict[str, list[dict]] = field(default_factory=dict, init=False)
    _latest: dict[str, EntryV2ShadowCapture] = field(default_factory=dict, init=False)
    _history: list[EntryV2ShadowCapture] = field(default_factory=list, init=False)
    _cycle_count: int = 0

    def install(self) -> "EntryV2RuntimeCapture":
        if self._original_fetch_strategy_data is not None:
            return self
        self._original_fetch_strategy_data = self.legacy.fetch_strategy_data

        def _capture_fetch():
            data = self._original_fetch_strategy_data()
            try:
                tickers, candles_15m, candles_5m = data
                self._last_tickers = dict(tickers or {})
                self._last_candles_15m = dict(candles_15m or {})
                self._last_candles_5m = dict(candles_5m or {})
            except (TypeError, ValueError):
                # Preserve the existing runtime return contract even if a future
                # legacy adapter changes its tuple shape.
                self._last_tickers = {}
                self._last_candles_15m = {}
                self._last_candles_5m = {}
            return data

        self.legacy.fetch_strategy_data = _capture_fetch
        return self

    def capture_cycle(self) -> dict[str, Any]:
        """Capture the just-completed scan; never alter its execution result."""
        self._cycle_count += 1
        cycle_records: dict[str, EntryV2ShadowCapture] = {}
        btc = dict(self.btc_guard_provider() if self.btc_guard_provider else {})
        btc_guard = "REJECT" if bool(btc.get("crashing")) else "PASS"

        for symbol, legacy_result in (getattr(self.legacy, "latest_scores", {}) or {}).items():
            ticker = self._last_tickers.get(symbol, {}) or {}
            candles_15m = self._last_candles_15m.get(symbol, []) or []
            candles_5m = self._last_candles_5m.get(symbol, []) or []
            context = self.mtf_candles.get(symbol, {}) or {}
            candles_1h = context.get("1h", []) or []
            candles_4h = context.get("4h", []) or []

            price = float(legacy_result.get("price", ticker.get("lastPrice", 0.0)) or 0.0)
            atr = float(legacy_result.get("atr", 0.0) or 0.0)
            stop_distance_percent = (2.0 * atr / price * 100.0) if price > 0 and atr > 0 else 0.0
            bid = float(ticker.get("bidPrice", price) or price)
            ask = float(ticker.get("askPrice", price) or price)
            spread_percent = ((ask - bid) / price * 100.0) if price > 0 else 0.0

            # Entry v2 currently has no authoritative target/reward source in
            # the active legacy path. Keep it explicitly pending instead of
            # copying the older core strategy's take-profit formula.
            facts = EntryV2MarketFacts(
                legacy_result=legacy_result,
                candles_5m=candles_5m,
                candles_15m=candles_15m,
                candles_1h=candles_1h,
                candles_4h=candles_4h,
                stop_distance_percent=stop_distance_percent,
                reward_risk=None,
                spread_percent=spread_percent,
                btc_guard=btc_guard,
            )

            # All evaluated symbols are retained for observability, but the V2
            # decision is meaningful as an entry comparison only when the legacy
            # lane actually proposed a buy. HOLD observations remain available as
            # raw evidence without fabricating a lane.
            is_candidate = bool(
                legacy_result.get("signal") == "BUY"
                or legacy_result.get("scalp_signal") == "BUY"
                or legacy_result.get("swing_signal") == "BUY"
            )
            if not is_candidate:
                continue

            capture = capture_entry_v2(symbol, facts)
            cycle_records[str(symbol).upper()] = capture
            self._latest[str(symbol).upper()] = capture
            self._history.append(capture)

            trace = self.runtime.last_entry_diagnostics.setdefault(str(symbol).upper(), {"symbol": str(symbol).upper()})
            summary = capture_summary(capture)
            trace["entry_v2_shadow"] = {
                "v2_decision": summary["v2_decision"],
                "v2_trade_mode": summary["v2_trade_mode"],
                "v2_setup_type": summary["v2_setup_type"],
                "v2_failed_gate": summary["v2_failed_gate"],
                "v2_approved": summary["v2_approved"],
                "legacy_signal": summary["legacy_signal"],
                "legacy_trade_mode": summary["legacy_trade_mode"],
                "legacy_score": summary["legacy_score"],
                "legacy_scalp_score": summary["legacy_scalp_score"],
                "legacy_swing_score": summary["legacy_swing_score"],
            }

        if len(self._history) > self.max_history:
            del self._history[:-self.max_history]
        return self.summary(cycle_records)

    def summary(self, cycle_records: Mapping[str, EntryV2ShadowCapture] | None = None) -> dict[str, Any]:
        records = list(cycle_records.values()) if cycle_records is not None else list(self._latest.values())
        legacy_rows = list((getattr(self.legacy, "latest_scores", {}) or {}).values())
        approved = sum(1 for item in records if item.v2_decision.get("approved") is True)
        rejected = sum(1 for item in records if item.v2_decision.get("approved") is False)
        return {
            "schema_version": 1,
            "cycle": self._cycle_count,
            "evaluated_symbols": len(legacy_rows),
            "legacy_buy_candidates": sum(
                1
                for row in legacy_rows
                if row.get("signal") == "BUY"
                or row.get("scalp_signal") == "BUY"
                or row.get("swing_signal") == "BUY"
            ),
            "captured_candidates": len(records),
            "v2_approved": approved,
            "v2_rejected": rejected,
            "v2_reward_risk_pending": sum(1 for item in records if item.v2_decision.get("failed_gate") == "REWARD_RISK_PENDING"),
            "latest": {
                symbol: {
                    "legacy_signal": item.legacy_result.get("signal"),
                    "legacy_trade_mode": item.legacy_result.get("trade_mode"),
                    "v2_decision": item.v2_decision.get("decision"),
                    "v2_trade_mode": item.v2_decision.get("trade_mode"),
                    "v2_setup_type": item.v2_decision.get("setup_type"),
                    "v2_failed_gate": item.v2_decision.get("failed_gate"),
                }
                for symbol, item in self._latest.items()
            },
        }

    def latest_captures(self) -> dict[str, dict[str, Any]]:
        return {symbol: capture.to_dict() for symbol, capture in self._latest.items()}


def install(*, legacy: Any, runtime: Any, mtf_candles: Mapping[str, Mapping[str, list[dict]]], trading_symbols: list[str], btc_guard_provider: Callable[[], Mapping[str, Any]] | None = None, max_history: int = 500) -> EntryV2RuntimeCapture:
    capture = EntryV2RuntimeCapture(
        legacy=legacy,
        runtime=runtime,
        mtf_candles=mtf_candles,
        trading_symbols=list(trading_symbols),
        btc_guard_provider=btc_guard_provider,
        max_history=max_history,
    )
    return capture.install()
