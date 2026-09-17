"""Side-by-side replay helper for Legacy vs Entry v2.

No exchange calls, persistence writes, or trade execution are performed here.
The helper accepts already-recorded legacy strategy observations and the
corresponding market facts, then returns auditable comparison rows and a
compact summary of how Entry v2 changes the legacy decision flow.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .entry_v2_adapter import EntryV2MarketFacts, build_entry_scenario, evaluate_legacy_with_entry_v2


@dataclass(frozen=True)
class ReplayRow:
    symbol: str
    legacy_decision: str
    legacy_trade_mode: str
    legacy_score: float | None
    v2_decision: str
    v2_trade_mode: str
    v2_setup_type: str | None
    v2_failed_gate: str | None
    v2_passed_gates: tuple[str, ...]
    candle_patterns_5m: tuple[str, ...]
    candle_patterns_15m: tuple[str, ...]
    candle_patterns_1h: tuple[str, ...]
    candle_patterns_4h: tuple[str, ...]


@dataclass(frozen=True)
class ReplaySummary:
    total_cases: int
    legacy_buys: int
    legacy_holds: int
    v2_approved: int
    v2_rejected: int
    legacy_buy_v2_rejected: int
    legacy_buy_v2_approved: int
    v2_decision_counts: Mapping[str, int]
    v2_lane_counts: Mapping[str, int]
    v2_setup_counts: Mapping[str, int]


def replay_one(symbol: str, facts: EntryV2MarketFacts) -> ReplayRow:
    legacy: Mapping[str, Any] = facts.legacy_result
    decision = evaluate_legacy_with_entry_v2(facts)
    scenario = build_entry_scenario(facts)
    by_tf = scenario["structure"]["multi_candle_by_timeframe"]
    legacy_mode = str(legacy.get("trade_mode", "NONE")).upper()
    legacy_signal = str(legacy.get("signal", "HOLD")).upper()
    legacy_decision = "BUY" if legacy_mode in {"SCALP", "SWING"} and legacy_signal == "BUY" else "HOLD"

    return ReplayRow(
        symbol=symbol,
        legacy_decision=legacy_decision,
        legacy_trade_mode=legacy_mode,
        legacy_score=float(legacy["score"]) if legacy.get("score") is not None else None,
        v2_decision=decision.decision,
        v2_trade_mode=decision.trade_mode,
        v2_setup_type=decision.setup_type,
        v2_failed_gate=decision.failed_gate,
        v2_passed_gates=decision.passed_gates,
        candle_patterns_5m=tuple(str(value) for value in by_tf.get("5m", {}).get("patterns", ())),
        candle_patterns_15m=tuple(str(value) for value in by_tf.get("15m", {}).get("patterns", ())),
        candle_patterns_1h=tuple(str(value) for value in by_tf.get("1h", {}).get("patterns", ())),
        candle_patterns_4h=tuple(str(value) for value in by_tf.get("4h", {}).get("patterns", ())),
    )


def replay_many(cases: Mapping[str, EntryV2MarketFacts]) -> list[ReplayRow]:
    return [replay_one(symbol, facts) for symbol, facts in cases.items()]


def summarize_replay(rows: Sequence[ReplayRow]) -> ReplaySummary:
    legacy_buys = sum(row.legacy_decision == "BUY" for row in rows)
    v2_approved = sum(row.v2_decision.startswith("APPROVED_") for row in rows)
    return ReplaySummary(
        total_cases=len(rows),
        legacy_buys=legacy_buys,
        legacy_holds=sum(row.legacy_decision == "HOLD" for row in rows),
        v2_approved=v2_approved,
        v2_rejected=len(rows) - v2_approved,
        legacy_buy_v2_rejected=sum(row.legacy_decision == "BUY" and not row.v2_decision.startswith("APPROVED_") for row in rows),
        legacy_buy_v2_approved=sum(row.legacy_decision == "BUY" and row.v2_decision.startswith("APPROVED_") for row in rows),
        v2_decision_counts=dict(Counter(row.v2_decision for row in rows)),
        v2_lane_counts=dict(Counter(row.v2_trade_mode for row in rows)),
        v2_setup_counts=dict(Counter(row.v2_setup_type or "NONE" for row in rows)),
    )
